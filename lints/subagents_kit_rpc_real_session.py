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
CHILD_TEXT = "KIT_RPC_CHILD_TEXT"
CHILD_DONE = "rpc probe done"
CHILD_FAILED = "rpc probe failed"
FAIL_MARKER = "KIT_RPC_PROBE_FAIL"
FAILURE_TEXT = "kit rpc boom"
REQUIRED_FEATURES = {"get", "list", "kit-schedule", "kit-workflow"}
KIT_LABEL = "(kit 分支)"

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
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const terminal = new Set(["completed", "steered", "aborted", "stopped", "error"]);
  async function settled(description, limitMs) {
    const seen = [];
    const deadline = Date.now() + limitMs;
    for (;;) {
      const reply = await call("list");
      const agent = (reply?.data?.agents ?? []).find((item) => item.description === description);
      if (agent) seen.push(agent.status);
      if (agent && terminal.has(agent.status)) return { agent, seen, timeout: false };
      if (Date.now() > deadline) return { agent: agent ?? null, seen, timeout: true };
      await sleep(200);
    }
  }
  pi.registerTool({
    name: "probe_rpc",
    label: "Probe Rpc",
    description: "probe",
    parameters: Type.Object({ description: Type.String() }),
    async execute(_toolCallId, params) {
      const ping = await call("ping");
      const { agent, seen, timeout } = await settled(params.description, 30000);
      const get = agent ? await call("get", { agentId: agent.id }) : null;
      const missing = await call("get", { agentId: "nope" });
      return { content: [{ type: "text", text: JSON.stringify({ ping, agent, get, missing, seen, timeout }) }] };
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
        if metadata["version"] != installed_version:
            return fallback(f"{branch} 分支基线 {metadata['version']} 与已安装 {installed_version} 不一致")
        archive = kit_git(repo, "archive", branch, "src")
        head = kit_git(repo, "rev-parse", "--short", branch).decode().strip()
        scratch = Path(tempfile.mkdtemp(prefix="kit-subagents-src-"))
        package = scratch / "node_modules/@tintinweb/pi-subagents"
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps(metadata))
        subprocess.run(["tar", "-x", "-C", str(package)], input=archive, check=True)
        for name in metadata.get("dependencies", {}):
            target = scratch / "node_modules" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(installed / name, target)
        return package / "src/index.ts", f"{branch}@{head}{KIT_LABEL}", scratch
    except (subprocess.CalledProcessError, KeyError, OSError):
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
        return fallback(f"{branch} 分支取不出 src")


def user_text(request: dict) -> str:
    return " ".join(str(message.get("content")) for message in request.get("messages") or [] if message.get("role") == "user")


def answered_count(request: dict) -> int:
    return sum(1 for message in request.get("messages") or [] if message.get("role") == "tool")


def next_call(answered: int) -> tuple[str, dict] | None:
    if answered == 0:
        return "Agent", {"prompt": f"{CHILD_MARKER}: report done", "description": CHILD_DONE, "subagent_type": "general-purpose"}
    if answered == 1:
        return "probe_rpc", {"description": CHILD_DONE}
    if answered == 2:
        return "Agent", {"prompt": f"{FAIL_MARKER}: report done", "description": CHILD_FAILED, "subagent_type": "general-purpose"}
    if answered == 3:
        return "probe_rpc", {"description": CHILD_FAILED}
    return None


def probe_results(requests: list[dict]) -> list[dict]:
    parents = [request for request in requests if CHILD_MARKER not in user_text(request) and FAIL_MARKER not in user_text(request)]
    if not parents:
        return []
    return [
        json.loads(message["content"])
        for message in parents[-1].get("messages") or []
        if message.get("role") == "tool" and '"ping"' in str(message.get("content"))
    ]


class ScriptedModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_body(self, body: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_failure(self):
        body = json.dumps({"error": {"message": FAILURE_TEXT, "type": "server_error"}}).encode()
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
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
            self.send_failure()
            return
        if CHILD_MARKER in prompt:
            deltas, finish = [{"role": "assistant", "content": CHILD_TEXT}], "stop"
        else:
            call = next_call(answered_count(request))
            if call is None:
                deltas, finish = [{"role": "assistant", "content": FINAL_TEXT}], "stop"
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
    for path in (home, agent_dir, ext_dir / "node_modules", scratch):
        path.mkdir(parents=True)
    (ext_dir / "probe.ts").write_text(PROBE)
    os.symlink(package_root / "node_modules" / "typebox", ext_dir / "node_modules" / "typebox")
    (agent_dir / "models.json").write_text(
        json.dumps({"providers": {PROVIDER: {"baseUrl": f"http://127.0.0.1:{server.server_address[1]}/v1", "api": "openai-completions", "apiKey": "scripted", "models": [{"id": "scripted"}]}}})
    )
    (agent_dir / "settings.json").write_text(json.dumps({"retry": {"enabled": False}}))
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


def lint(pi: str, package_root: Path, subagents: Path, source: str) -> list[str]:
    problems = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    server.requests = []
    server.state_lock = threading.Lock()
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
    probes = probe_results(server.requests)
    if len(probes) != 2:
        return problems + [f"探针应取样完成与失败两个子代理的终态快照,实际 {len(probes)} 份: {stderr.strip()[-300:]}"]
    done, failed = probes
    ping = done["ping"]
    features = set((ping.get("data") or {}).get("features") or [])
    if not ping.get("success") or not REQUIRED_FEATURES <= features:
        problems.append(f"ping 没有报出 kit 补丁的能力面(应有 {sorted(REQUIRED_FEATURES)}): {json.dumps(ping, ensure_ascii=False)[:300]}")
    agent = done.get("agent") or {}
    if not agent.get("id") or not agent.get("sessionId") or agent.get("type") != "general-purpose":
        problems.append(f"list 没有给出带 id/sessionId/type 的子代理快照: {json.dumps(done, ensure_ascii=False)[:300]}")
        return problems
    got = done["get"]
    if not got.get("success") or (got.get("data") or {}).get("agent", {}).get("id") != agent.get("id"):
        problems.append(f"get 没有按 id 取回同一份快照: {json.dumps(got, ensure_ascii=False)[:300]}")
    missing = done["missing"]
    if missing.get("success") is not False or "not found" not in str(missing.get("error", "")).lower():
        problems.append(f"get 不存在的 id 应报 Agent not found: {json.dumps(missing, ensure_ascii=False)[:200]}")
    if not source.endswith(KIT_LABEL):
        return problems
    if agent.get("status") != "completed" or CHILD_TEXT not in str(agent.get("result")) or "error" in agent:
        problems.append(f"完成的子代理应把最终正文带回 result 且不带 error: {json.dumps(agent, ensure_ascii=False)[:300]}")
    failed_agent = failed.get("agent") or {}
    if failed_agent.get("status") != "error" or FAILURE_TEXT not in str(failed_agent.get("error")):
        problems.append(f"失败的子代理应把失败原因带回 error: {json.dumps(failed_agent, ensure_ascii=False)[:300]}")
    return problems


if __name__ == "__main__":
    pi = pi_binary()
    if pi is None:
        print("subagents_kit_rpc_real_session: skip(默认路径下无 pi)")
        sys.exit(0)
    package_root = pi_package_root(pi)
    entry, source, scratch = resolve_entry()
    if package_root is None or entry is None:
        print("subagents_kit_rpc_real_session: skip(找不到 pi 包根目录或 pi-subagents)")
        sys.exit(0)
    try:
        found = lint(pi, package_root, entry, source)
    except (RuntimeError, json.JSONDecodeError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(f"subagents_kit_rpc_real_session: E2E 执行失败: {error}")
        sys.exit(1)
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
    for item in found:
        print(f"subagents_kit_rpc_real_session: {item}")
    print(f"subagents_kit_rpc_real_session: ok(被测源 {source})" if not found else "")
    sys.exit(1 if found else 0)
