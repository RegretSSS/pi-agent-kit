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
PROVIDER = "notifyswallow"
FINAL_TEXT = "NOTIFY_SWALLOW_DONE"
MARK = "NOTIFY_SWALLOW_MARK"
NOTIFY = "后台任务结束"
TASK_SECONDS = 3
HOLD_SECONDS = 3.2
SCENES = {
    "wait": {"requests": 3, "arrives": 2, "tools": ["task_create", "bg_status"], "note": "bg_status 的 wait 抢先结算了退出,完成通知被吞"},
    "query": {"requests": 4, "arrives": 3, "tools": ["task_create", "bash", "bg_list"], "note": "任务退出后紧接着的 bg_list 抢先结算了退出,完成通知被吞"},
}


def pi_binary() -> str | None:
    found = shutil.which("pi")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "pi"
    return str(fallback) if fallback.exists() else None


def pi_package_root(pi: str) -> Path | None:
    for parent in Path(pi).resolve().parents:
        if (parent / "node_modules" / "typebox" / "package.json").exists():
            return parent
    return None


def scene_of(request: dict) -> str:
    text = " ".join(str(message.get("content")) for message in request.get("messages") or [] if message.get("role") == "user" and NOTIFY not in str(message.get("content")))
    return next((name for name in SCENES if f"SCENE_{name}" in text), "")


def tool_results(request: dict) -> list[str]:
    return [str(message.get("content")) for message in request.get("messages") or [] if message.get("role") == "tool"]


def notify_count(request: dict) -> int:
    return sum(1 for message in request.get("messages") or [] if message.get("role") == "user" and NOTIFY in json.dumps(message.get("content"), ensure_ascii=False))


def called_tools(requests: list[dict]) -> list[str]:
    return [call["function"]["name"] for request in requests for message in request.get("messages") or [] if message.get("role") == "assistant" for call in message.get("tool_calls") or []]


def notify_text(requests: list[dict]) -> str:
    return " ".join(json.dumps(message.get("content"), ensure_ascii=False) for request in requests for message in request.get("messages") or [] if message.get("role") == "user" and NOTIFY in json.dumps(message.get("content"), ensure_ascii=False))


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
        request = json.loads(raw or b"{}")
        with self.server.state_lock:
            self.server.requests.append(request)
            index = len(self.server.requests)
        scene, answered = scene_of(request), len(tool_results(request))
        call = None
        if answered == 0:
            call = ("task_create", {"cmd": f"sleep {TASK_SECONDS}; echo {MARK}; exit 5", "name": "notify-swallow"})
        elif scene == "wait" and answered == 1:
            found = re.search(r"\b(\d{14}-\d+-[a-z0-9]+)\b", tool_results(request)[0])
            call = ("bg_status", {"handle": f"task:{found.group(1)}", "wait": 120}) if found else None
        elif scene == "query" and answered == 1:
            call = ("bash", {"command": f"sleep {HOLD_SECONDS}"})
        elif scene == "query" and answered == 2:
            call = ("bg_list", {})
        if call is None:
            deltas, finish = [{"role": "assistant", "content": FINAL_TEXT}], "stop"
        else:
            deltas = [
                {"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": f"call_{index}", "type": "function", "function": {"name": call[0], "arguments": ""}}]},
                {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(call[1])}}]},
            ]
            finish = "tool_calls"
        chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
        body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_session(pi: str, package_root: Path, server: ThreadingHTTPServer, scene: str) -> list[dict]:
    before = len(server.requests)
    with tempfile.TemporaryDirectory(prefix="tasks-notify-swallow-") as tmp:
        home, agent_dir, ext_dir, scratch = (Path(tmp) / name for name in ("home", "agent", "ext", "scratch"))
        for path in (home, agent_dir, ext_dir / "node_modules", scratch, scratch / "tmp"):
            path.mkdir(parents=True)
        shutil.copyfile(ROOT / "extensions" / "tasks.ts", ext_dir / "tasks.ts")
        os.symlink(package_root / "node_modules" / "typebox", ext_dir / "node_modules" / "typebox")
        (agent_dir / "models.json").write_text(json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}}))
        (agent_dir / "settings.json").write_text(json.dumps({"retry": {"enabled": False}}))
        result = subprocess.run(
            [
                pi, "--provider", PROVIDER, "--model", "scripted", "--offline", "--no-extensions", "-e", str(ext_dir / "tasks.ts"),
                "--no-session", "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--mode", "json", "-p", f"run the scripted calls SCENE_{scene}",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            cwd=scratch,
            timeout=120,
            env={**os.environ, "HOME": str(home), "PI_CODING_AGENT_DIR": str(agent_dir), "TMPDIR": str(scratch / "tmp")},
        )
    if result.returncode != 0:
        raise RuntimeError(f"pi 退出码 {result.returncode}: {result.stderr[-600:]}")
    if re.search(r"(extension|tasks)[^\n]*(error|failed)", result.stderr, re.IGNORECASE):
        raise RuntimeError(f"真实会话里扩展报错: {result.stderr.strip()[-400:]}")
    return server.requests[before:]


def scene_problems(scene: str, requests: list[dict]) -> list[str]:
    rule = SCENES[scene]
    problem = f"SCENE_{scene}({' → '.join(rule['tools'])}):{rule['note']}"
    hits = [notify_count(request) for request in requests]
    if sum(hits) != 1:
        return [f"{problem}——完成通知应恰好送达 1 次,实际 {sum(hits)} 次(各请求 {hits})"]
    if len(requests) != rule["requests"] or hits[rule["arrives"]] != 1:
        return [f"{problem}——通知应随第 {rule['arrives'] + 1} 次模型请求送达且不多唤醒一次,实际共 {len(requests)} 次请求(各请求 {hits})"]
    if MARK not in notify_text(requests):
        return [f"{problem}——通知应带任务尾部日志({MARK})"]
    if scene == "wait":
        status = next((text for text in tool_results(requests[-1]) if "waited=" in text), "")
        if "exit=code=5" not in status:
            return [f"{problem}——bg_status(wait) 应等到退出并报真实退出码 5: {status[:200]}"]
    return []


def lint(pi: str, package_root: Path) -> list[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.requests = []
    server.state_lock = threading.Lock()
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        sessions = {scene: run_session(pi, package_root, server, scene) for scene in SCENES}
    finally:
        server.shutdown()
        server.server_close()
    problems = []
    for scene, requests in sessions.items():
        problems.extend(scene_problems(scene, requests))
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    if pi is None:
        print("tasks_notify_not_swallowed_by_bg_query: skip(默认路径下无 pi)")
        sys.exit(0)
    package_root = pi_package_root(pi)
    if package_root is None:
        print("tasks_notify_not_swallowed_by_bg_query: skip(找不到 pi 包根目录,typebox 无法解析)")
        sys.exit(0)
    try:
        found = lint(pi, package_root)
    except (RuntimeError, json.JSONDecodeError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(f"tasks_notify_not_swallowed_by_bg_query: E2E 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"tasks_notify_not_swallowed_by_bg_query: {item}")
    print("tasks_notify_not_swallowed_by_bg_query: ok" if not found else "")
    sys.exit(1 if found else 0)
