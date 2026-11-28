#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MB = 1024 * 1024
LINE = "[apigate] 收到 429：该调用让出并发槽排队等待，并发容量降为 1（30 秒后重试）"
PROVIDER = "piguardsim"
FINAL_TEXT = "PI_GUARD_REAL_SESSION_DONE"


def pi_binary() -> str | None:
    found = shutil.which("pi")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "pi"
    return str(fallback) if fallback.exists() else None


def unavailable(pi: str | None) -> str | None:
    if pi is None:
        return "默认路径下无 pi"
    if not os.environ.get("XDG_RUNTIME_DIR"):
        return "无 XDG_RUNTIME_DIR(无用户级 systemd 总线)"
    if shutil.which("systemd-run") is None:
        return "无 systemd-run"
    if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
        return "无 cgroup v2"
    return None


class ScriptedModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"object": "list", "data": [{"id": "scripted", "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        answered = sum(1 for message in request.get("messages") or [] if message.get("role") == "tool")
        commands = self.server.commands
        if answered < len(commands):
            deltas = [
                {"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": f"call_{answered}", "type": "function", "function": {"name": "bash", "arguments": ""}}]},
                {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps({"command": commands[answered]})}}]},
            ]
            finish = "tool_calls"
        else:
            deltas = [{"role": "assistant", "content": FINAL_TEXT}]
            finish = "stop"
        chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
        chunks.append({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(commands: list[str]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.commands = commands
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def slice_path(slice_name: str) -> Path | None:
    probe = subprocess.run(
        ["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit=pi-guard-lint-probe-{os.getpid()}", f"--slice={slice_name}", "--", "/bin/cat", "/proc/self/cgroup"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    match = re.search(r"^0::(\S+)$", probe.stdout, re.MULTILINE)
    if probe.returncode != 0 or match is None:
        return None
    path = Path("/sys/fs/cgroup", match.group(1).strip("/").rsplit("/", 1)[0])
    return path if (path / "cgroup.procs").exists() else None


def limit_probe(slice_dir: Path) -> str:
    return f"b=$(cat {slice_dir}/memory.max); echo max > {slice_dir}/memory.max; echo max > {slice_dir}/memory.swap.max; sleep 1; a=$(cat {slice_dir}/memory.max); w=$(cat {slice_dir}/memory.swap.max); sleep 2; echo \"GUARDLIMIT before=$b after=$a swap=$w cg=$(cut -d: -f3 /proc/self/cgroup)\""


def hot_loop(seconds: int) -> str:
    return "python3 - <<'EOF' 2>&1\nimport sys, time\nend = time.time() + %d\nblock = (%r + \"\\n\") * 100\nwhile time.time() < end:\n    sys.stdout.write(block)\n    time.sleep(0.005)\nEOF" % (seconds, LINE)


def run_session(pi: str, server: ThreadingHTTPServer, config: dict, workdir: Path) -> tuple[list[dict], str]:
    agent_dir = workdir / "agent"
    log_dir = workdir / "log"
    spill_dir = workdir / "tmp"
    config_file = workdir / "pi-guard.json"
    for path in (agent_dir, log_dir, spill_dir):
        path.mkdir()
    (agent_dir / "models.json").write_text(
        json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}})
    )
    config_file.write_text(json.dumps(config))
    result = subprocess.run(
        [
            pi, "--provider", PROVIDER, "--model", "scripted", "--offline", "--no-extensions", "-e", str(ROOT / "extensions" / "pi-guard.ts"),
            "--no-session", "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--mode", "json", "-p", "run the scripted calls",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=workdir,
        timeout=150,
        env={**os.environ, "PI_CODING_AGENT_DIR": str(agent_dir), "PI_GUARD_CONFIG": str(config_file), "PI_GUARD_LOG_DIR": str(log_dir), "TMPDIR": str(spill_dir)},
    )
    if result.returncode != 0:
        raise RuntimeError(f"pi 退出码 {result.returncode}: {result.stderr[-600:]}")
    events = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events, result.stderr, sorted(path.name for path in spill_dir.glob("pi-*.log"))


def text_of(result: dict) -> str:
    return "\n".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")


def exit_code_of(result: dict) -> int | None:
    code = result.get("structuredContent", {}).get("exit_code")
    return code if isinstance(code, int) else None


def lint(pi: str) -> list[str]:
    problems = []
    slice_name = f"piguardreal{os.getpid()}.slice"
    limit = 600 * MB
    slice_dir = slice_path(slice_name)
    try:
        if slice_dir is None:
            return [f"用户级 systemd 不可用,无法定位测试 slice {slice_name}"]
        server = serve([limit_probe(slice_dir), hot_loop(10)])
        try:
            with tempfile.TemporaryDirectory(prefix="pi-guard-real-session-") as tmp:
                config = {"slice": slice_name, "sliceMaxBytes": limit, "spinWindowSec": 3, "tickMs": 50, "rateWindowMs": 500, "reportMinSec": 0}
                events, stderr, leftovers = run_session(pi, server, config, Path(tmp))
                log_file = Path(tmp) / "log" / "log.jsonl"
                logged = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()] if log_file.exists() else []
        finally:
            server.shutdown()
            server.server_close()
    finally:
        subprocess.run(["systemctl", "--user", "stop", slice_name], capture_output=True)
    if re.search(r"(extension|pi-guard)[^\n]*(error|failed)", stderr, re.IGNORECASE):
        problems.append(f"真实会话里扩展报错: {stderr.strip()[-400:]}")
    if leftovers:
        problems.append(f"会话结束后临时目录里留下了输出转存件: {leftovers}")
    ends = [event for event in events if event.get("type") == "tool_execution_end"]
    if len(ends) != 2:
        problems.append(f"脚本化会话应执行两条命令,实际 {len(ends)} 条: {stderr.strip()[-300:]}")
        return problems
    probe = ends[0]["result"]
    probe_text = text_of(probe)
    found = re.search(r"GUARDLIMIT before=(\S+) after=(\S+) swap=(\S+) cg=(\S+)", probe_text)
    if found is None:
        problems.append(f"未取到命令自身的限额读数: {probe_text[:200]!r}")
    else:
        before, after, swap, cgroup = found.groups()
        if before != str(limit):
            problems.append(f"命令运行期间 slice 限额不在位: {before}")
        if after != str(limit) or swap != "0":
            problems.append(f"限额被重置后未在一个采样节拍内补回: after={after} swap={swap}")
        if f"/{slice_name}/pi-guard-" not in cgroup or not cgroup.endswith(".scope"):
            problems.append(f"命令没有跑在测试 slice 的 scope 里: {cgroup}")
    if exit_code_of(probe) != 0:
        problems.append(f"限额自检命令应以 0 退出: {exit_code_of(probe)}")
    if "[pi-guard] 用量:" not in probe_text:
        problems.append("真实会话里没有采样到命令(缺用量回执)——跟踪未建立")
    spin = ends[1]["result"]
    spin_text = text_of(spin)
    if exit_code_of(spin) != 137 or "[pi-guard] 已停止:空转热循环" not in spin_text or "已折叠" not in spin_text:
        problems.append(f"真实会话里空转热循环未被停止或未折叠回执: exit={exit_code_of(spin)}")
    if ends[1].get("durationMs", 0) > 9500:
        problems.append(f"真实会话里空转判定过慢: {ends[1].get('durationMs')}ms")
    spilled = re.search(r"转存件\((\d+)MB", spin_text)
    if spilled is None or int(spilled.group(1)) < 1:
        problems.append(f"被停的热循环留下的转存件没有被删除,回执也没说明: {spin_text[-300:]!r}")
    if any(line.get("mode") != "contained" or not line.get("unit", "").startswith("pi-guard-") for line in logged):
        problems.append(f"日志未记录 contained 模式与 unit: {logged}")
    if not any(line.get("verdict") == "normal" and line.get("durationMs", 0) >= 2900 for line in logged):
        problems.append(f"历时 ≥2s 的普通命令未落日志: {logged}")
    spins = [line for line in logged if line.get("verdict") == "spin"]
    if len(spins) != 1 or spins[0].get("action") != "kill-spin":
        problems.append(f"空转裁决未入日志: {[(line.get('verdict'), line.get('action')) for line in logged]}")
    replies = [event["message"] for event in events if event.get("type") == "message_end" and event.get("message", {}).get("role") == "assistant"]
    last_reply = " ".join(part.get("text", "") for part in replies[-1].get("content", []) if isinstance(part, dict)) if replies else ""
    if last_reply.strip() != FINAL_TEXT:
        problems.append(f"会话没有正常收尾: {last_reply[:80]!r}")
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    reason = unavailable(pi)
    if reason:
        print(f"pi_guard_real_session: skip({reason})")
        sys.exit(0)
    try:
        found = lint(pi)
    except (RuntimeError, json.JSONDecodeError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(f"pi_guard_real_session: E2E 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"pi_guard_real_session: {item}")
    print("pi_guard_real_session: ok" if not found else "")
    sys.exit(1 if found else 0)
