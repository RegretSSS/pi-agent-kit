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
PROVIDER = "tasknotifysim"
FINAL_TEXT = "TASK_NOTIFY_IN_TURN_DONE"
MARKER = "notify-in-turn-marker"
HOLD_SECONDS = 6


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
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.requests.append(raw)
        request = json.loads(raw or b"{}")
        answered = sum(1 for message in request.get("messages") or [] if message.get("role") == "tool")
        if answered == 0:
            call = {"name": "task_create", "arguments": json.dumps({"cmd": f"sleep 1.5; echo {MARKER}", "name": "in-turn-probe"})}
        elif answered == 1:
            call = {"name": "bash", "arguments": json.dumps({"command": f"sleep {HOLD_SECONDS}"})}
        else:
            call = None
        if call is None:
            deltas = [{"role": "assistant", "content": FINAL_TEXT}]
            finish = "stop"
        else:
            deltas = [
                {"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": f"call_{answered}", "type": "function", "function": {"name": call["name"], "arguments": ""}}]},
                {"tool_calls": [{"index": 0, "function": {"arguments": call["arguments"]}}]},
            ]
            finish = "tool_calls"
        chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
        chunks.append({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_session(pi: str, package_root: Path, server: ThreadingHTTPServer, workdir: Path) -> str:
    home = workdir / "home"
    agent_dir = workdir / "agent"
    ext_dir = workdir / "ext"
    scratch = workdir / "scratch"
    for path in (home, agent_dir, ext_dir / "node_modules", scratch):
        path.mkdir(parents=True)
    shutil.copyfile(ROOT / "extensions" / "tasks.ts", ext_dir / "tasks.ts")
    os.symlink(package_root / "node_modules" / "typebox", ext_dir / "node_modules" / "typebox")
    (agent_dir / "models.json").write_text(
        json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}})
    )
    result = subprocess.run(
        [
            pi, "--provider", PROVIDER, "--model", "scripted", "--offline", "--no-extensions", "-e", str(ext_dir / "tasks.ts"),
            "--no-session", "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--mode", "json", "-p", "run the scripted calls",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=scratch,
        timeout=120,
        env={**os.environ, "HOME": str(home), "PI_CODING_AGENT_DIR": str(agent_dir)},
    )
    if result.returncode != 0:
        raise RuntimeError(f"pi 退出码 {result.returncode}: {result.stderr[-600:]}")
    return result.stderr


def lint(pi: str, package_root: Path) -> list[str]:
    problems = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.requests = []
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="tasks-notify-in-turn-") as tmp:
            stderr = run_session(pi, package_root, server, Path(tmp))
    finally:
        server.shutdown()
        server.server_close()
    requests = [json.loads(raw) for raw in server.requests]
    if re.search(r"(extension|tasks)[^\n]*(error|failed)", stderr, re.IGNORECASE):
        problems.append(f"真实会话里扩展报错: {stderr.strip()[-400:]}")
    if len(requests) != 3:
        problems.append(f"脚本化会话应有 3 次模型请求(task_create → bash 占位 → 收尾),实际 {len(requests)} 次——通知若是回合结束后才到,会多出一次被通知触发的请求")
        return problems
    third = json.dumps(requests[2]["messages"], ensure_ascii=False)
    second = json.dumps(requests[1]["messages"], ensure_ascii=False)
    if "后台任务结束" in second:
        problems.append("通知早于任务退出就出现在第 2 次请求里")
    if "后台任务结束" not in third or MARKER not in third:
        problems.append(f"回合进行中(模型未轮询)通知没有送达第 3 次请求: 末尾消息 {third[-300:]!r}")
    called = [call["function"]["name"] for request in requests for message in request["messages"] if message.get("role") == "assistant" for call in message.get("tool_calls") or []]
    if "task_output" in called:
        problems.append("脚本化模型不应轮询,却出现了 task_output")
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    if pi is None:
        print("tasks_notify_in_turn_real_session: skip(默认路径下无 pi)")
        sys.exit(0)
    package_root = pi_package_root(pi)
    if package_root is None:
        print("tasks_notify_in_turn_real_session: skip(找不到 pi 包根目录,typebox 无法解析)")
        sys.exit(0)
    try:
        found = lint(pi, package_root)
    except (RuntimeError, json.JSONDecodeError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(f"tasks_notify_in_turn_real_session: E2E 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"tasks_notify_in_turn_real_session: {item}")
    print("tasks_notify_in_turn_real_session: ok" if not found else "")
    sys.exit(1 if found else 0)
