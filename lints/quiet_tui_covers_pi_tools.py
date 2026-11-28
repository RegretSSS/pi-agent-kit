#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "quiet_tui_driver.mjs"
PROVIDER = "quiettuicovers"
ACTIVATED_BUILTINS = ["+codemode", "+grep", "+find", "+ls", "+powershell"]


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
        with self.server.state_lock:
            self.server.requests.append(json.loads(raw or b"{}"))
        chunk = {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}]}
        body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def tool_names(request: dict) -> list[str]:
    return sorted(tool["function"]["name"] for tool in request.get("tools") or [])


def active_tools(pi: str, server: ThreadingHTTPServer) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="kit-quiet-tui-covers-") as tmp:
        home, agent_dir, scratch = (Path(tmp) / name for name in ("home", "agent", "scratch"))
        for path in (home, agent_dir, scratch):
            path.mkdir(parents=True)
        (agent_dir / "models.json").write_text(json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}}))
        (agent_dir / "settings.json").write_text(json.dumps({"defaultTools": ACTIVATED_BUILTINS}))
        result = subprocess.run(
            [pi, "--provider", PROVIDER, "--model", "scripted", "--offline", "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--mode", "json", "-p", "hi"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            cwd=scratch,
            timeout=120,
            env={**os.environ, "HOME": str(home), "PI_CODING_AGENT_DIR": str(agent_dir)},
        )
    if result.returncode != 0:
        raise RuntimeError(f"pi 退出码 {result.returncode}: {result.stderr[-600:]}")
    if not server.requests:
        raise RuntimeError("脚本化会话没有留下请求")
    return tool_names(server.requests[0])


def taken_over() -> list[str]:
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(DRIVER), "pure"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:])
    return json.loads(result.stdout)["pure"]["builtins"]


def lint(pi: str) -> list[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.requests = []
    server.state_lock = threading.Lock()
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        names = active_tools(pi, server)
    finally:
        server.shutdown()
        server.server_close()
    taken = set(taken_over())
    problems = [f"pi 激活的工具 {name!r} 不在 quiet-tui 的接管名单里,它在 TUI 里不会折叠成单行" for name in names if name not in taken]
    missing = [name.lstrip("+") for name in ACTIVATED_BUILTINS if name.lstrip("+") not in names]
    if missing:
        problems.append(f"全开名单没能激活 {missing},pi 可能改名、移除或改成默认激活了它们,核对后更新 ACTIVATED_BUILTINS: 实际工具 {names}")
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    if pi is None or pi_package_root(pi) is None or shutil.which("node") is None:
        print("quiet_tui_covers_pi_tools: skip(无 node 或无 pi)")
        sys.exit(0)
    try:
        found = lint(pi)
    except (RuntimeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"quiet_tui_covers_pi_tools: 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"quiet_tui_covers_pi_tools: {item}")
    print("quiet_tui_covers_pi_tools: ok(pi 的内建工具全开时都在接管名单里)" if not found else "")
    sys.exit(1 if found else 0)
