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
PROVIDER = "quiettuisim"
COMMAND = "printf 'E2E_MARK\\n'; for i in 1 2 3; do printf 'line %s\\n' $i; done; exit 0"
FINAL_TEXT = "QUIET_TUI_PROBE_DONE"


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


def tool_results(request: dict) -> list[str]:
    return [str(message.get("content")) for message in request.get("messages") or [] if message.get("role") == "tool"]


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
        if tool_results(request):
            deltas, finish = [{"role": "assistant", "content": FINAL_TEXT}], "stop"
        else:
            deltas = [
                {"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": f"call_{index}", "type": "function", "function": {"name": "bash", "arguments": ""}}]},
                {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps({"command": COMMAND})}}]},
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


def run_session(pi: str, package_root: Path, server: ThreadingHTTPServer, workdir: Path, quiet: Path | None) -> str:
    home, agent_dir, ext_dir, scratch = (workdir / name for name in ("home", "agent", "ext", "scratch"))
    for path in (home, agent_dir, ext_dir / "node_modules", scratch):
        path.mkdir(parents=True)
    os.symlink(package_root / "node_modules" / "typebox", ext_dir / "node_modules" / "typebox")
    if quiet is not None:
        shutil.copyfile(quiet, ext_dir / "quiet-tui.ts")
    (agent_dir / "models.json").write_text(json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}}))
    extensions = ["--no-extensions"] + ([] if quiet is None else ["-e", str(ext_dir / "quiet-tui.ts")])
    result = subprocess.run(
        [pi, "--provider", PROVIDER, "--model", "scripted", "--offline", *extensions, "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--mode", "json", "-p", "run the probe"],
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


def session_output(pi: str, package_root: Path, server: ThreadingHTTPServer, quiet: Path | None) -> list[str]:
    before = len(server.requests)
    with tempfile.TemporaryDirectory(prefix="kit-quiet-tui-") as tmp:
        stderr = run_session(pi, package_root, server, Path(tmp), quiet)
    requests = server.requests[before:]
    if not requests:
        raise RuntimeError("脚本化会话没有留下请求")
    results = tool_results(requests[-1])
    if len(results) != 1:
        raise RuntimeError(f"会话应恰有 1 次工具调用,实际 {len(results)} 次")
    if re.search(r"quiet-tui[^\n]*(error|failed)", stderr, re.IGNORECASE):
        raise RuntimeError(f"quiet-tui 加载报错: {stderr.strip()[-400:]}")
    return results


def lint(pi: str, package_root: Path) -> list[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.requests = []
    server.state_lock = threading.Lock()
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        bare = session_output(pi, package_root, server, None)
        quiet = session_output(pi, package_root, server, ROOT / "extensions" / "quiet-tui.ts")
    finally:
        server.shutdown()
        server.server_close()
    problems = []
    if quiet != bare:
        problems.append(f"加载 quiet-tui 后模型可见的工具结果变了: 对照 {bare} | 实测 {quiet}")
    if "E2E_MARK" not in quiet[0] or "line 3" not in quiet[0]:
        problems.append(f"工具结果应原样到达模型: {quiet}")
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    package_root = pi_package_root(pi) if pi else None
    if pi is None or package_root is None:
        print("quiet_tui_real_session: skip(无 pi)")
        sys.exit(0)
    try:
        found = lint(pi, package_root)
    except (RuntimeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"quiet_tui_real_session: E2E 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"quiet_tui_real_session: {item}")
    print(f"quiet_tui_real_session: ok(有/无 quiet-tui 两个会话,模型可见结果一致)" if not found else "")
    sys.exit(1 if found else 0)
