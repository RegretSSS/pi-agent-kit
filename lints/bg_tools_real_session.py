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
PROVIDER = "bgtoolssim"
FINAL_TEXT = "BG_TOOLS_PROBE_DONE"
CHILD_MARKER = "BG_TOOLS_CHILD_MARKER"
CHILD_DONE = "BG_CHILD_DONE"
CHILD_OK = "bg probe child"
CHILD_FAILED = "bg fail child"
FAIL_MARKER = "BG_TOOLS_FAIL_CHILD"
FAILURE_TEXT = "bg tools boom"
TASK_MARK = "BG_TASK_MARK"
KIT_LABEL = "(kit 分支)"


def pi_binary() -> str | None:
    found = shutil.which("pi")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "pi"
    return str(fallback) if fallback.exists() else None


def pi_package_root(pi: str) -> Path | None:
    resolved = Path(pi).resolve()
    for parent in resolved.parents:
        if (parent / "node_modules" / "typebox" / "package.json").exists():
            return parent
    return None


def kit_git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def resolve_entry() -> tuple[Path | None, str, Path | None]:
    override = os.environ.get("KIT_SUBAGENTS_SRC")
    if override:
        return Path(override), f"KIT_SUBAGENTS_SRC={override}", None
    installed = Path.home() / ".pi/agent/npm/node_modules"
    deployed = installed / "@tintinweb/pi-subagents"
    repo = Path(os.environ.get("PI_SUBAGENTS_KIT") or Path.home() / "workspace/pi-subagents-kit")
    branch = os.environ.get("PI_SUBAGENTS_KIT_BRANCH") or "kit"
    entry = deployed / "src/index.ts"

    def fallback(note: str) -> tuple[Path | None, str, Path | None]:
        return (entry if entry.exists() else None), f"部署位({note})", None

    if not repo.exists() or not (deployed / "package.json").exists():
        return fallback("本机无 kit 分支仓库" if not repo.exists() else "pi-subagents 未安装")
    scratch = None
    try:
        metadata = json.loads(kit_git(repo, "show", f"{branch}:package.json"))
        installed_version = json.loads((deployed / "package.json").read_text())["version"]
        baseline = os.environ.get("PI_SUBAGENTS_KIT_BASELINE") or installed_version
        if metadata["version"] != baseline:
            return fallback(f"{branch} 分支基线 {metadata['version']} 与期望基线 {baseline}(已安装 {installed_version})不一致")
        tracked = kit_git(repo, "ls-tree", "--name-only", branch).decode().split()
        archive = kit_git(repo, "archive", branch, *[name for name in ("src", "skills") if name in tracked])
        head = kit_git(repo, "rev-parse", "--short", branch).decode().strip()
        scratch = Path(tempfile.mkdtemp(prefix="kit-subagents-src-"))
        package = scratch / "node_modules/@tintinweb/pi-subagents"
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps(metadata))
        subprocess.run(["tar", "-x", "-C", str(package)], input=archive, check=True)
        dep_root = Path(os.environ.get("PI_SUBAGENTS_DEP_ROOT") or installed)
        for name in metadata.get("dependencies", {}):
            target = scratch / "node_modules" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(dep_root / name if (dep_root / name).exists() else installed / name, target)
        return package / "src/index.ts", f"{branch}@{head}·基线{metadata['version']}{KIT_LABEL}", scratch
    except (subprocess.CalledProcessError, KeyError, OSError):
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
        return fallback(f"{branch} 分支取不出 src")


def user_text(request: dict) -> str:
    return " ".join(str(message.get("content")) for message in request.get("messages") or [] if message.get("role") == "user")


def tool_results(request: dict) -> list[str]:
    return [str(message.get("content")) for message in request.get("messages") or [] if message.get("role") == "tool"]


def agent_id(listing: str, description: str) -> str | None:
    found = re.search(rf"^agent:([0-9A-Za-z-]+)[^\n]*\| {re.escape(description)}\s*$", listing, re.MULTILINE)
    return found.group(1) if found else None


def next_call(request: dict) -> tuple[str, dict] | None:
    results = tool_results(request)
    answered = len(results)
    if answered == 0:
        return "task_create", {"cmd": f"sleep 4; echo {TASK_MARK}; exit 5", "name": "bg-e2e"}
    if answered == 1:
        return "Agent", {"prompt": f"{CHILD_MARKER}: run the bash command `sleep 2`, then reply with exactly {CHILD_DONE}", "description": CHILD_OK, "subagent_type": "general-purpose"}
    if answered == 2:
        return "Agent", {"prompt": f"{FAIL_MARKER}: report done", "description": CHILD_FAILED, "subagent_type": "general-purpose"}
    if answered == 3:
        return "bg_list", {}
    child, failed = agent_id(results[3], CHILD_OK), agent_id(results[3], CHILD_FAILED)
    task = re.search(r"task:(\d{14}-\d+-[a-z0-9]+)", results[3])
    if answered == 4:
        return ("bg_status", {"handle": f"agent:{child}", "wait": 30}) if child else None
    if answered == 5:
        return ("bg_log", {"handle": f"agent:{child}"}) if child else None
    if answered == 6:
        return ("bg_status", {"handle": f"agent:{failed}", "wait": 30}) if failed else None
    if answered == 7:
        return ("bg_status", {"handle": f"task:{task.group(1)}", "wait": 30}) if task else None
    if answered == 8:
        return ("bg_log", {"handle": f"task:{task.group(1)}"}) if task else None
    if answered == 9:
        return ("bg_stop", {"handle": f"task:{task.group(1)}"}) if task else None
    if answered == 10:
        return "bg_schedule", {"action": "list"}
    return None


class ScriptedModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_body(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_body(json.dumps({"object": "list", "data": [{"id": "scripted", "object": "model"}]}).encode(), "application/json")

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        request = json.loads(raw or b"{}")
        with self.server.state_lock:
            self.server.requests.append(request)
            index = len(self.server.requests)
        prompt = user_text(request)
        if FAIL_MARKER in prompt:
            self.send_body(json.dumps({"error": {"message": FAILURE_TEXT, "type": "server_error"}}).encode(), "application/json", 500)
            return
        if CHILD_MARKER in prompt:
            call = ("bash", {"command": "sleep 2"}) if not tool_results(request) else None
        else:
            call = next_call(request)
        if call is None:
            deltas = [{"role": "assistant", "content": CHILD_DONE if CHILD_MARKER in prompt else FINAL_TEXT}]
            finish = "stop"
        else:
            name, arguments = call
            deltas = [
                {"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": f"call_{index}", "type": "function", "function": {"name": name, "arguments": ""}}]},
                {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(arguments)}}]},
            ]
            finish = "tool_calls"
        chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
        chunks.append({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
        self.send_body(body, "text/event-stream")


def run_session(pi: str, package_root: Path, subagents: Path, server: ThreadingHTTPServer, workdir: Path) -> str:
    home = workdir / "home"
    agent_dir = workdir / "agent"
    ext_dir = workdir / "ext"
    scratch = workdir / "scratch"
    for path in (home, agent_dir, ext_dir / "node_modules", scratch, scratch / "tmp"):
        path.mkdir(parents=True)
    shutil.copyfile(ROOT / "extensions" / "tasks.ts", ext_dir / "tasks.ts")
    os.symlink(package_root / "node_modules" / "typebox", ext_dir / "node_modules" / "typebox")
    (agent_dir / "models.json").write_text(
        json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}})
    )
    (agent_dir / "settings.json").write_text(json.dumps({"retry": {"enabled": False}}))
    result = subprocess.run(
        [
            pi, "--provider", PROVIDER, "--model", "scripted", "--offline", "--no-extensions", "-e", str(subagents), "-e", str(ext_dir / "tasks.ts"),
            "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--mode", "json", "-p", "run the probe",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=scratch,
        timeout=150,
        env={**os.environ, "HOME": str(home), "PI_CODING_AGENT_DIR": str(agent_dir), "TMPDIR": str(scratch / "tmp")},
    )
    if result.returncode != 0:
        raise RuntimeError(f"pi 退出码 {result.returncode}: {result.stderr[-600:]}")
    return result.stderr


def lint(pi: str, package_root: Path, subagents: Path, source: str) -> list[str]:
    problems = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.requests = []
    server.state_lock = threading.Lock()
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="kit-bg-") as tmp:
            stderr = run_session(pi, package_root, subagents, server, Path(tmp))
            exit_files = [path for path in (Path(tmp) / "home" / ".agents" / "tasks").glob("*.exit")]
            exit_codes = [path.read_text().strip() for path in exit_files]
    finally:
        server.shutdown()
        server.server_close()
    if re.search(r"(extension|tasks|subagents)[^\n]*(error|failed)", stderr, re.IGNORECASE):
        problems.append(f"真实会话里扩展报错: {stderr.strip()[-400:]}")
    parents = [request for request in server.requests if CHILD_MARKER not in user_text(request) and FAIL_MARKER not in user_text(request)]
    if not parents:
        return problems + ["脚本化会话没有留下父会话请求"]
    results = tool_results(parents[-1])
    if len(results) != 11:
        return problems + [f"脚本化会话应走完 11 次工具调用,实际 {len(results)} 次: {json.dumps(parents[-1].get('messages'), ensure_ascii=False)[-600:]}"]
    listing, agent_status, agent_log, failed_status, task_status, task_log, stopped, jobs = results[3:11]
    if "[task]" not in listing or "[agent]" not in listing or "task:" not in listing or "agent:" not in listing:
        problems.append(f"bg_list 没有同时列出命令任务与子代理: {listing[:300]}")
    if "completed" not in agent_status:
        problems.append(f"bg_status(agent) 应报 completed: {agent_status[:300]}")
    if "[bash]" not in agent_log or "[cursor=" not in agent_log:
        problems.append(f"bg_log(agent) 应给出子代理会话记录与游标: {agent_log[:300]}")
    if "exit=code=5" not in task_status:
        problems.append(f"bg_status(task, wait) 应等到退出并报真实退出码 5: {task_status[:300]}")
    if TASK_MARK not in task_log or "[cursor=" not in task_log:
        problems.append(f"bg_log(task) 应读到命令输出与游标: {task_log[:300]}")
    if "幂等跳过" not in stopped:
        problems.append(f"bg_stop 对已退出任务应幂等跳过: {stopped[:300]}")
    if "无定时任务" not in jobs:
        problems.append(f"bg_schedule list 应回显空清单: {jobs[:300]}")
    if exit_codes != ["5"]:
        problems.append(f"任务应把自己的退出码落到 <id>.exit: {exit_codes}")
    if not source.endswith(KIT_LABEL):
        return problems
    if "result(尾" not in agent_status or CHILD_DONE not in agent_status:
        problems.append(f"bg_status(agent) 应给出子代理结论的尾部: {agent_status[:300]}")
    child = agent_id(listing, CHILD_OK) or ""
    if not re.search(rf"^标签: {re.escape(CHILD_OK)} · agent · 父:[0-9a-f]{{8}} · general-purpose#{child[:8]}$", agent_status, re.MULTILINE):
        problems.append(f"bg_status(agent) 应原样给出子代理会话的标签: {agent_status[:300]}")
    if "| error |" not in failed_status or "error:" not in failed_status or FAILURE_TEXT not in failed_status or "result(" in failed_status:
        problems.append(f"bg_status(失败的子代理) 应给出失败原因且不给空的 result 行: {failed_status[:300]}")
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    if pi is None:
        print("bg_tools_real_session: skip(默认路径下无 pi)")
        sys.exit(0)
    package_root = pi_package_root(pi)
    entry, source, scratch = resolve_entry()
    if package_root is None or entry is None:
        print("bg_tools_real_session: skip(找不到 pi 包根目录或 pi-subagents)")
        sys.exit(0)
    try:
        found = lint(pi, package_root, entry, source)
    except (RuntimeError, json.JSONDecodeError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(f"bg_tools_real_session: E2E 执行失败: {error}")
        sys.exit(1)
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
    for item in found:
        print(f"bg_tools_real_session: {item}")
    print(f"bg_tools_real_session: ok(被测源 {source})" if not found else "")
    sys.exit(1 if found else 0)
