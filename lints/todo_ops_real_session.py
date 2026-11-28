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
PROVIDER = "todoopsim"
FINAL_TEXT = "TODO_OPS_DONE"
LEGACY_WRITER = """import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	pi.registerTool({
		name: "legacy_todo",
		label: "Legacy todo",
		description: "Writes a full todo-state snapshot the way the todo extension did before it switched to per-operation entries",
		promptSnippet: "legacy todo",
		parameters: Type.Object({}),
		async execute() {
			pi.appendEntry("todo-state", { todos: [{ id: 1, text: "legacy one", status: "pending" }, { id: 2, text: "legacy two", status: "in_progress" }], nextId: 3, settledDone: 4, settledPending: 0 });
			return { content: [{ type: "text", text: "legacy snapshot written" }], details: {} };
		},
	});
}
"""


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
        messages = request.get("messages") or []
        turn_start = max((index for index, message in enumerate(messages) if message.get("role") == "user"), default=-1)
        answered = sum(1 for message in messages[turn_start + 1 :] if message.get("role") == "tool")
        call = self.server.script[answered] if answered < len(self.server.script) else None
        if call is None:
            deltas = [{"role": "assistant", "content": FINAL_TEXT}]
            finish = "stop"
        else:
            name, arguments = call
            deltas = [
                {"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": f"call_{answered}", "type": "function", "function": {"name": name, "arguments": ""}}]},
                {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(arguments, ensure_ascii=False)}}]},
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


def run_session(pi: str, package_root: Path, server: ThreadingHTTPServer, workdir: Path, script: list, extensions: list[Path], session: Path | None = None) -> str:
    scratch = workdir / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "tmp").mkdir(exist_ok=True)
    server.requests = []
    server.script = script
    command = [
        pi, "--provider", PROVIDER, "--model", "scripted", "--offline", "--no-extensions",
        "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--mode", "json", "-p", "run the scripted calls",
    ]
    for path in extensions:
        command += ["-e", str(path)]
    if session is not None:
        command += ["--session", str(session)]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=scratch,
        timeout=120,
        env={**os.environ, "HOME": str(workdir / "home"), "PI_CODING_AGENT_DIR": str(workdir / "agent"), "TMPDIR": str(scratch / "tmp")},
    )
    if result.returncode != 0:
        raise RuntimeError(f"pi 退出码 {result.returncode}: {result.stderr[-600:]}")
    return result.stderr


def last_request_text(server: ThreadingHTTPServer) -> str:
    return json.dumps(json.loads(server.requests[-1])["messages"], ensure_ascii=False)


def lint(pi: str, package_root: Path) -> list[str]:
    problems = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="todo-ops-") as tmp:
            workdir = Path(tmp)
            home = workdir / "home"
            agent_dir = workdir / "agent"
            ext_dir = workdir / "ext"
            for path in (home, agent_dir, ext_dir / "node_modules"):
                path.mkdir(parents=True)
            (ext_dir / "legacy.ts").write_text(LEGACY_WRITER)
            shutil.copyfile(ROOT / "extensions" / "todo.ts", ext_dir / "todo.ts")
            os.symlink(package_root / "node_modules" / "typebox", ext_dir / "node_modules" / "typebox")
            (agent_dir / "models.json").write_text(
                json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}})
            )
            stderr = run_session(pi, package_root, server, workdir, [("legacy_todo", {})], [ext_dir / "legacy.ts"])
            if re.search(r"(extension|legacy)[^\n]*(error|failed)", stderr, re.IGNORECASE):
                problems.append(f"旧版写法的桩扩展报错: {stderr.strip()[-400:]}")
            sessions = sorted((agent_dir / "sessions").rglob("*.jsonl"))
            if len(sessions) != 1:
                return problems + [f"第一阶段应恰好留下 1 个会话文件,实际 {len(sessions)} 个"]
            session = sessions[0]
            stderr = run_session(pi, package_root, server, workdir, [("todo", {"action": "add", "text": "new three"}), ("todo", {"action": "list"})], [ext_dir / "todo.ts"], session)
            if re.search(r"(extension|todo)[^\n]*(error|failed)", stderr, re.IGNORECASE):
                problems.append(f"续接旧会话时 todo 扩展报错: {stderr.strip()[-400:]}")
            upgraded = last_request_text(server)
            for needle in ("[ ] #1: legacy one", "[>] #2: legacy two", "[ ] #3: new three", "已完成 4 · 未完成 3"):
                if needle not in upgraded:
                    problems.append(f"新版没有在旧的全量快照之上续写:第 2 阶段的清单缺 {needle!r}: {upgraded[-400:]}")
            stderr = run_session(pi, package_root, server, workdir, [("todo", {"action": "toggle", "id": 1}), ("todo", {"action": "list"})], [ext_dir / "todo.ts"], session)
            if re.search(r"(extension|todo)[^\n]*(error|failed)", stderr, re.IGNORECASE):
                problems.append(f"重启后再续接时 todo 扩展报错: {stderr.strip()[-400:]}")
            restarted = last_request_text(server)
            for needle in ("[x] #1: legacy one", "[ ] #3: new three", "已完成 5 · 未完成 2"):
                if needle not in restarted:
                    problems.append(f"重启后增量没有回放出来:第 3 阶段的清单缺 {needle!r}: {restarted[-400:]}")
            lines = session.read_text().splitlines()
            snapshots = [line for line in lines if '"customType":"todo-state"' in line]
            operations = [line for line in lines if '"customType":"todo-op"' in line]
            if len(snapshots) != 1:
                problems.append(f"会话文件里的全量快照条目应只有旧版写的那 1 条,实际 {len(snapshots)} 条——新版仍在整表重写")
            if [json.loads(line)["data"] | {"doneAt": 0} for line in operations] != [{"op": "add", "id": 3, "text": "new three"} | {"doneAt": 0}, {"op": "status", "id": 1, "status": "done"} | {"doneAt": 0}]:
                problems.append(f"会话文件里的增量条目与执行过的操作不一致: {operations}")
            biggest = max((len(line.encode()) for line in operations), default=0)
            if biggest >= 400:
                problems.append(f"单条增量条目过大({biggest} 字节)——增量应只含这次操作本身")
    finally:
        server.shutdown()
        server.server_close()
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    if pi is None:
        print("todo_ops_real_session: skip(默认路径下无 pi)")
        sys.exit(0)
    package_root = pi_package_root(pi)
    if package_root is None:
        print("todo_ops_real_session: skip(找不到 pi 包根目录,typebox 无法解析)")
        sys.exit(0)
    try:
        found = lint(pi, package_root)
    except (RuntimeError, json.JSONDecodeError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(f"todo_ops_real_session: E2E 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"todo_ops_real_session: {item}")
    print("todo_ops_real_session: ok" if not found else "")
    sys.exit(1 if found else 0)
