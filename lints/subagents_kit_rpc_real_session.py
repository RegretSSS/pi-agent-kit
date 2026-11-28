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
PROVIDER = "kitrpcsim"
FINAL_TEXT = "KIT_RPC_PROBE_DONE"
CHILD_MARKER = "KIT_RPC_PROBE_CHILD"
REQUIRED_FEATURES = {"get", "list", "kit-schedule", "kit-workflow"}

PROBE = '''import { randomUUID } from "node:crypto";
import { Type } from "typebox";

export default function (pi) {
  const call = (method, params = {}) =>
    new Promise((resolve) => {
      const requestId = randomUUID();
      const off = pi.events.on(`subagents:rpc:${method}:reply:${requestId}`, (reply) => {
        off();
        resolve(reply);
      });
      setTimeout(() => {
        off();
        resolve({ success: false, error: "no reply" });
      }, 3000);
      pi.events.emit(`subagents:rpc:${method}`, { requestId, ...params });
    });
  pi.registerTool({
    name: "probe_rpc",
    label: "Probe Rpc",
    description: "probe",
    parameters: Type.Object({}),
    async execute() {
      const ping = await call("ping");
      const list = await call("list");
      const first = list?.data?.agents?.[0]?.id;
      const get = first ? await call("get", { agentId: first }) : null;
      const missing = await call("get", { agentId: "nope" });
      return { content: [{ type: "text", text: JSON.stringify({ ping, list, get, missing }) }] };
    },
  });
}
'''


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


def subagents_entry() -> Path | None:
    override = os.environ.get("KIT_SUBAGENTS_SRC")
    if override:
        return Path(override)
    entry = Path.home() / ".pi/agent/npm/node_modules/@tintinweb/pi-subagents/src/index.ts"
    return entry if entry.exists() else None


def is_child_request(request: dict) -> bool:
    return any(message.get("role") == "user" and CHILD_MARKER in json.dumps(message.get("content"), ensure_ascii=False) for message in request.get("messages") or [])


def probe_result(requests: list[dict]) -> dict | None:
    for request in requests:
        for message in request.get("messages") or []:
            if message.get("role") == "tool" and '"ping"' in str(message.get("content")):
                return json.loads(message["content"])
    return None


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

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        request = json.loads(raw or b"{}")
        self.server.requests.append(request)
        messages = request.get("messages") or []
        answered = sum(1 for message in messages if message.get("role") == "tool")
        if is_child_request(request) or answered >= 2:
            deltas = [{"role": "assistant", "content": FINAL_TEXT}]
            finish = "stop"
        else:
            name, arguments = (
                ("Agent", {"prompt": f"{CHILD_MARKER}: report done", "description": "rpc probe child", "subagent_type": "general-purpose"})
                if answered == 0
                else ("probe_rpc", {})
            )
            deltas = [
                {"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": f"call_{len(self.server.requests)}", "type": "function", "function": {"name": name, "arguments": ""}}]},
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
    for path in (home, agent_dir, ext_dir / "node_modules", scratch):
        path.mkdir(parents=True)
    (ext_dir / "probe.ts").write_text(PROBE)
    os.symlink(package_root / "node_modules" / "typebox", ext_dir / "node_modules" / "typebox")
    (agent_dir / "models.json").write_text(
        json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}})
    )
    result = subprocess.run(
        [
            pi, "--provider", PROVIDER, "--model", "scripted", "--offline", "--no-extensions", "-e", str(subagents), "-e", str(ext_dir / "probe.ts"),
            "--no-session", "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--mode", "json", "-p", "run the probe",
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


def lint(pi: str, package_root: Path, subagents: Path) -> list[str]:
    problems = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.requests = []
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="kit-rpc-") as tmp:
            stderr = run_session(pi, package_root, subagents, server, Path(tmp))
    finally:
        server.shutdown()
        server.server_close()
    if re.search(r"(extension|probe|subagents)[^\n]*(error|failed)", stderr, re.IGNORECASE):
        problems.append(f"真实会话里扩展报错: {stderr.strip()[-400:]}")
    found = probe_result(server.requests)
    if found is None:
        return problems + [f"probe_rpc 没有拿到回复: {stderr.strip()[-300:]}"]
    ping = found["ping"]
    features = set((ping.get("data") or {}).get("features") or [])
    if not ping.get("success") or not REQUIRED_FEATURES <= features:
        problems.append(f"ping 没有报出 kit 补丁的能力面(应有 {sorted(REQUIRED_FEATURES)}): {json.dumps(ping, ensure_ascii=False)[:300]}")
    listing = found["list"]
    agents = (listing.get("data") or {}).get("agents") or []
    if not listing.get("success") or not agents:
        problems.append(f"list 没有返回子代理快照: {json.dumps(listing, ensure_ascii=False)[:300]}")
        return problems
    first = agents[0]
    if not first.get("id") or not first.get("sessionId") or first.get("type") != "general-purpose":
        problems.append(f"快照缺字段或类型不对(应有 id/sessionId/type): {json.dumps(first, ensure_ascii=False)[:300]}")
    got = found["get"]
    if not got.get("success") or (got.get("data") or {}).get("agent", {}).get("id") != first.get("id"):
        problems.append(f"get 没有按 id 取回同一份快照: {json.dumps(got, ensure_ascii=False)[:300]}")
    missing = found["missing"]
    if missing.get("success") is not False or "not found" not in str(missing.get("error", "")).lower():
        problems.append(f"get 不存在的 id 应报 Agent not found: {json.dumps(missing, ensure_ascii=False)[:200]}")
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    if pi is None:
        print("subagents_kit_rpc_real_session: skip(默认路径下无 pi)")
        sys.exit(0)
    package_root = pi_package_root(pi)
    subagents = subagents_entry()
    if package_root is None or subagents is None:
        print("subagents_kit_rpc_real_session: skip(找不到 pi 包根目录或 pi-subagents)")
        sys.exit(0)
    try:
        found = lint(pi, package_root, subagents)
    except (RuntimeError, json.JSONDecodeError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(f"subagents_kit_rpc_real_session: E2E 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"subagents_kit_rpc_real_session: {item}")
    print("subagents_kit_rpc_real_session: ok" if not found else "")
    sys.exit(1 if found else 0)
