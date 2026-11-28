#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROVIDER = "subagentscopesim"
FINAL_TEXT = "TASK_SUBAGENT_SCOPE_DONE"
CHILD_MARKER = "CHILD_PROBE_MARKER"
NOTIFY = "后台任务结束"
PHASED_NAME = "exit-phased"
CHILD_STARTUP_SECONDS = 0.08


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


def subagents_entry(home: Path) -> Path | None:
    entry = home / ".pi/agent/npm/node_modules/@tintinweb/pi-subagents/src/index.ts"
    return entry if entry.exists() else None


def is_child_request(request: dict) -> bool:
    return any(message.get("role") == "user" and CHILD_MARKER in json.dumps(message.get("content"), ensure_ascii=False) for message in request.get("messages") or [])


def phased_exit_time(mark_time: float, child_request_time: float, now: float) -> float:
    child_tick = (child_request_time - CHILD_STARTUP_SECONDS - mark_time) % 2
    target = mark_time + (child_tick - 1) % 2
    while target < now + 0.6:
        target += 2
    return target


class ScriptedModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_body(self, body: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_body(json.dumps({"object": "list", "data": [{"id": "scripted", "object": "model"}]}).encode(), "application/json")

    def parent_calls(self, answered: int) -> list[tuple[str, dict]]:
        if answered == 0:
            return [("task_create", {"cmd": "sleep 2; exit 0", "name": "phase-probe"})]
        if answered == 1:
            return [("bash", {"command": "sleep 5"})]
        if answered == 2:
            return [
                ("Agent", {"prompt": f"{CHILD_MARKER}: hold for a while, then report done ({index})", "description": f"scope probe child {index}", "subagent_type": "general-purpose"})
                for index in (1, 2)
            ]
        if answered == 4:
            return [("bash", {"command": "sleep 1"})]
        if answered == 5:
            with self.server.state_lock:
                mark_time = self.server.mark_time
                arrivals = list(self.server.child_arrivals)
            if mark_time is None or not arrivals:
                self.server.phase_unknown = True
                return [("task_create", {"cmd": "sleep 3; exit 0", "name": PHASED_NAME})]
            target = phased_exit_time(mark_time, max(arrivals), time.time())
            return [("task_create", {"cmd": f"python3 -I -c 'import time; time.sleep(max(0, {target!r} - time.time()))'", "name": PHASED_NAME})]
        if answered == 6:
            return [("bash", {"command": "sleep 14"})]
        return []

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        request = json.loads(raw or b"{}")
        messages = request.get("messages") or []
        answered = sum(1 for message in messages if message.get("role") == "tool")
        if is_child_request(request):
            with self.server.state_lock:
                self.server.child_arrivals.append(time.time())
            self.server.requests.append(request)
            calls = [("bash", {"command": "sleep 13"})] if answered == 0 else []
        else:
            self.server.requests.append(request)
            calls = self.parent_calls(answered)
        if not calls:
            deltas = [{"role": "assistant", "content": FINAL_TEXT}]
            finish = "stop"
        else:
            deltas = [
                {"role": "assistant", "content": "", "tool_calls": [{"index": index, "id": f"call_{len(self.server.requests)}_{index}", "type": "function", "function": {"name": name, "arguments": ""}} for index, (name, _) in enumerate(calls)]},
                {"tool_calls": [{"index": index, "function": {"arguments": json.dumps(arguments)}} for index, (_, arguments) in enumerate(calls)]},
            ]
            finish = "tool_calls"
        chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
        chunks.append({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
        self.send_body(body, "text/event-stream")


def watch_first_exit(journal: Path, state_lock: threading.Lock, state: dict) -> None:
    deadline = time.time() + 60
    while time.time() < deadline and state["mark_time"] is None:
        try:
            if '"kind":"exit"' in journal.read_text(errors="ignore"):
                with state_lock:
                    state["mark_time"] = time.time()
                return
        except OSError:
            pass
        time.sleep(0.02)


def run_session(pi: str, package_root: Path, subagents: Path, server: ThreadingHTTPServer, workdir: Path) -> str:
    home = workdir / "home"
    agent_dir = workdir / "agent"
    scratch = workdir / "scratch"
    for path in (home, agent_dir / "extensions", agent_dir / "node_modules", scratch):
        path.mkdir(parents=True)
    shutil.copyfile(ROOT / "extensions" / "tasks.ts", agent_dir / "extensions" / "tasks.ts")
    os.symlink(package_root / "node_modules" / "typebox", agent_dir / "node_modules" / "typebox")
    (agent_dir / "models.json").write_text(
        json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}})
    )
    result = subprocess.run(
        [
            pi, "--provider", PROVIDER, "--model", "scripted", "--offline", "--no-session", "--no-mcp", "--no-skills",
            "--no-prompt-templates", "--no-themes", "--no-context-files", "--mode", "json", "-p", "-e", str(subagents), "run the scripted calls",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=scratch,
        timeout=180,
        env={**os.environ, "HOME": str(home), "PI_CODING_AGENT_DIR": str(agent_dir)},
    )
    if result.returncode != 0:
        raise RuntimeError(f"pi 退出码 {result.returncode}: {result.stderr[-600:]}")
    return result.stderr


def lint(pi: str, package_root: Path, subagents: Path) -> list[str]:
    problems = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.requests = []
    server.state_lock = threading.Lock()
    server.child_arrivals = []
    server.mark_time = None
    server.phase_unknown = False
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="tasks-notify-subagent-") as tmp:
            watcher = threading.Thread(target=watch_first_exit, args=(Path(tmp) / "home/.agents/tasks/tasks.jsonl", server.state_lock, server.__dict__), daemon=True)
            watcher.start()
            stderr = run_session(pi, package_root, subagents, server, Path(tmp))
    finally:
        server.shutdown()
        server.server_close()
    if re.search(r"(extension|tasks|subagents)[^\n]*(error|failed)", stderr, re.IGNORECASE):
        problems.append(f"真实会话里扩展报错: {stderr.strip()[-400:]}")
    rendered = [(request, NOTIFY in json.dumps(request.get("messages"), ensure_ascii=False)) for request in server.requests]
    child_crossed = sum(1 for request, _ in rendered if is_child_request(request) and any(message.get("role") == "tool" for message in request.get("messages") or []))
    if server.phase_unknown or server.mark_time is None or child_crossed == 0:
        return [f"测试未生效(相位测得={server.mark_time is not None}, 子会话跨过退出时刻={child_crossed} 次)——场景没有跑到判别点: {stderr.strip()[-300:]}"]
    for request, notified in rendered:
        if notified and is_child_request(request):
            problems.append("父会话的后台任务结束通知被投进了子代理会话的上下文(判官串扰同款路径)")
    parent_last = [request for request, _ in rendered if not is_child_request(request)][-1]
    parent_text = json.dumps(parent_last.get("messages"), ensure_ascii=False)
    if NOTIFY not in parent_text or PHASED_NAME not in parent_text:
        problems.append("父会话没有在回合内收到自己后台任务的结束通知")
    called = [
        call["function"]["name"]
        for request, _ in rendered
        if not is_child_request(request)
        for message in request.get("messages") or []
        if message.get("role") == "assistant"
        for call in message.get("tool_calls") or []
    ]
    if "task_output" in called:
        problems.append("脚本化模型不应轮询,却出现了 task_output")
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    if pi is None:
        print("tasks_notify_subagent_real_session: skip(默认路径下无 pi)")
        sys.exit(0)
    package_root = pi_package_root(pi)
    subagents = subagents_entry(Path.home())
    if package_root is None or subagents is None:
        print("tasks_notify_subagent_real_session: skip(找不到 pi 包根目录或已安装的 pi-subagents)")
        sys.exit(0)
    try:
        found = lint(pi, package_root, subagents)
    except (RuntimeError, json.JSONDecodeError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(f"tasks_notify_subagent_real_session: E2E 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"tasks_notify_subagent_real_session: {item}")
    print("tasks_notify_subagent_real_session: ok" if not found else "")
    sys.exit(1 if found else 0)
