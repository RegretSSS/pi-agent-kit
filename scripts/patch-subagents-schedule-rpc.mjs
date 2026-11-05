import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const RPC_PATH = join(process.env.HOME, ".pi/agent/npm/node_modules/@tintinweb/pi-subagents/dist/cross-extension-rpc.js");
const INDEX_PATH = join(process.env.HOME, ".pi/agent/npm/node_modules/@tintinweb/pi-subagents/dist/index.js");

const RPC_ANCHOR = `    const unsubPing = handleRpc(events, "subagents:rpc:ping", () => {
        return { version: PROTOCOL_VERSION };
    });`;

const RPC_INJECT = `
    function requireScheduler() {
        const sched = deps.getScheduler?.();
        if (!sched) throw new Error("scheduler not active (no session bound yet)");
        return sched;
    }
    function noSuchJob(jobId) {
        throw new Error(\`no such job: \${jobId}\`);
    }
    const unsubScheduleList = handleRpc(events, "subagents:rpc:schedule_list", () => requireScheduler().list());
    const unsubScheduleRemove = handleRpc(events, "subagents:rpc:schedule_remove", ({ jobId }) => {
        if (!requireScheduler().removeJob(String(jobId))) noSuchJob(jobId);
        return undefined;
    });
    const unsubScheduleUpdate = handleRpc(events, "subagents:rpc:schedule_update", ({ jobId, patch }) => {
        const updated = requireScheduler().updateJob(String(jobId), patch || {});
        if (!updated) noSuchJob(jobId);
        return updated;
    });`;

const INDEX_ANCHOR = `            rpcHandle = registerRpcHandlers({
                events: pi.events,
                pi,
                getCtx: () => currentCtx,`;

const INDEX_INJECT = `                getScheduler: () => scheduler,`;

function patchFile(path, anchor, inject, marker, label) {
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
	const after = at + anchor.length;
	writeFileSync(path, text.slice(0, after) + inject + text.slice(after), "utf8");
	console.log(`patch-subagents: ${label} 注入完成`);
	return true;
}

const okRpc = patchFile(RPC_PATH, RPC_ANCHOR, RPC_INJECT, "subagents:rpc:schedule_list", "rpc-handlers");
const okIndex = patchFile(INDEX_PATH, INDEX_ANCHOR, INDEX_INJECT, "getScheduler: () => scheduler,", "getScheduler-dep");
process.exit(okRpc && okIndex ? 0 : 1);
