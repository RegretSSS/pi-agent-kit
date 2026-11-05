import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PKG = join(process.env.HOME ?? "", ".pi/agent/npm/node_modules/@tintinweb/pi-subagents");
const RPC_SRC = join(PKG, "src/cross-extension-rpc.ts");
const INDEX_SRC = join(PKG, "src/index.ts");

const RPC_PING_ANCHOR = `  const unsubPing = handleRpc(events, "subagents:rpc:ping", () => {
    return { version: PROTOCOL_VERSION };
  });`;

const RPC_INJECT = `${RPC_PING_ANCHOR}

  function requireScheduler(): any {
    const sched = deps.getScheduler?.();
    if (!sched) throw new Error("scheduler not active (no session bound yet)");
    return sched;
  }
  function noSuchJob(jobId: string): never {
    throw new Error(\`no such job: \${jobId}\`);
  }
  const unsubScheduleList = handleRpc(events, "subagents:rpc:schedule_list", () => requireScheduler().list());
  const unsubScheduleRemove = handleRpc(events, "subagents:rpc:schedule_remove", ({ jobId }: { jobId: string }) => {
    if (!requireScheduler().removeJob(String(jobId))) noSuchJob(jobId);
    return undefined;
  });
  const unsubScheduleUpdate = handleRpc(events, "subagents:rpc:schedule_update", ({ jobId, patch }: { jobId: string; patch: Record<string, unknown> }) => {
    const updated = requireScheduler().updateJob(String(jobId), patch || {});
    if (!updated) noSuchJob(jobId);
    return updated;
  });`;

const RPC_DEPS_ANCHOR = `  manager: SpawnCapable;
}`;
const RPC_DEPS_REPLACEMENT = `  getScheduler?: () => unknown;
  manager: SpawnCapable;
}`;

const INDEX_ANCHOR = `      rpcHandle = registerRpcHandlers({
        events: pi.events,
        pi,
        getCtx: () => currentCtx,`;
const INDEX_REPLACEMENT = `${INDEX_ANCHOR}
        getScheduler: () => scheduler,`;

function patchFile(path, anchor, replacement, marker, label) {
	let text;
	try {
		text = readFileSync(path, "utf8");
	} catch {
		console.error(`patch-subagents: 文件不存在 ${path}`);
		return false;
	}
	if (text.includes(marker)) {
		console.log(`patch-subagents: ${label} 已打过,跳过`);
		return true;
	}
	const at = text.indexOf(anchor);
	if (at < 0) {
		console.error(`patch-subagents: ${label} 锚点未命中(上游可能已升级),需人工复核 ${path}`);
		return false;
	}
	writeFileSync(path, text.slice(0, at) + replacement + text.slice(at + anchor.length), "utf8");
	console.log(`patch-subagents: ${label} 注入完成`);
	return true;
}

let ok = true;
ok = patchFile(RPC_SRC, RPC_DEPS_ANCHOR, RPC_DEPS_REPLACEMENT, "getScheduler?: () => unknown;", "rpc-deps") && ok;
ok = patchFile(RPC_SRC, RPC_PING_ANCHOR, RPC_INJECT, "subagents:rpc:schedule_list", "rpc-handlers") && ok;
ok = patchFile(INDEX_SRC, INDEX_ANCHOR, INDEX_REPLACEMENT, "getScheduler: () => scheduler,", "getScheduler-dep") && ok;
if (!ok) process.exit(1);

const jitiCache = join(tmpdir(), "jiti");
try {
	rmSync(jitiCache, { recursive: true, force: true });
	console.log(`patch-subagents: 已清理 jiti 编译缓存 ${jitiCache}(pi 经 jiti 加载 src/*.ts,patch 后必须清缓存否则旧编译产物复活)`);
} catch (error) {
	console.error(`patch-subagents: jiti 缓存清理失败 ${String(error)}`);
	process.exit(1);
}
