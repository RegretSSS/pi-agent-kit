import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PKG = join(process.env.HOME ?? "", ".pi/agent/npm/node_modules/@tintinweb/pi-subagents");
const RPC_SRC = join(PKG, "src/cross-extension-rpc.ts");
const INDEX_SRC = join(PKG, "src/index.ts");

const RPC_PING_ANCHOR = `  const unsubPing = handleRpc(events, "subagents:rpc:ping", () => {
    return { version: PROTOCOL_VERSION };
  });`;

const DESC_TAIL_ANCHOR = "stamp results after the workflow returns, or pass timestamps via args.`;";
const DESC_SLIM_EXPORT = `;

/**
 * Local kit patch (D12): progressive-disclosure slim description. The full
 * upstream text moved to the \`subagent-workflows\` skill (pattern library +
 * worked examples) and \`docs/workflows.md\` (API reference); this constant
 * keeps only the opt-in rules, a one-line-per-hook API summary, and the hard
 * runtime red lines. Re-runnable: the patch script rewrites this tail.
 */
export const slimWorkflowToolDescription = \`Execute a workflow script that orchestrates multiple subagents deterministically. Workflows run in the background — this tool returns immediately with a task ID, and you are notified when it completes. Use /agents → Workflows to watch live progress.

ONLY call this tool when the user has explicitly opted into multi-agent orchestration. Workflows can spawn dozens of agents and consume a large amount of tokens; the user must request that scale, not have it inferred. Explicit opt-in means one of:
- The user directly asked you to run a workflow or use multi-agent orchestration in their own words ("use a workflow", "run a workflow", "fan out agents", "orchestrate this with subagents"). The ask must be in the user's words — a task that would merely benefit from a workflow does not count.
- The user invoked a skill or slash command whose instructions tell you to call SubagentWorkflow.
- The user asked you to run a specific named or saved workflow.

For any other task — even one that would clearly benefit from parallelism — do NOT call this tool. Use the Agent tool for individual subagents, or describe what a workflow could do and what it would roughly cost, and ask the user whether to run it.

Before writing a script, read the skill \`subagent-workflows\` — it holds the routing table (when NOT to use a workflow), the pattern library (adversarial verify, judge panel, loop-until-dry, gate-and-retry, multi-modal sweep, completeness critic), topology and confirmation discipline, codemode integration, and worked-example pointers. Full API reference: \`~/.pi/agent/npm/node_modules/@tintinweb/pi-subagents/docs/workflows.md\`.

Script API summary (one line per hook; details in the skill/docs):
- Scripts are plain JavaScript, NOT TypeScript — type annotations and generics fail to parse. Async body: use await directly. \`Date.now()\`/\`Math.random()\`/argless \`new Date()\` throw (pass timestamps via \`args\`); \`eval\`/\`Function(...)\` throw; no filesystem or Node.js API access.
- Every script must begin with \`export const meta = { name, description, phases? }\` as a PURE literal (no variables/calls/spreads/interpolation); phase titles must match phase() calls exactly.
- agent(prompt, opts?): spawn a subagent. Without schema returns its final text; with schema (JSON Schema) returns a validated object; returns null on skip or terminal error — filter(Boolean) after every stage. opts: label, phase (use inside pipeline/parallel stages), schema, model (omit to inherit the session model), effort ('minimal'|'low'|'medium'|'high'|'xhigh'|'max'), isolation:'worktree' (expensive; parallel file mutation only), gate:'<command>' (non-zero exit fails the agent — prefer this over asking an agent whether code looks right), resume:'<label>' (continue that child's context; cannot combine with agentType/model/effort/isolation/gate/schema), agentType (custom type from the Agent tool registry):
{{typeList}}
- pipeline(items, stage1, ...): each item flows through all stages with NO barrier — the default for multi-stage work. Stage receives (prevResult, originalItem, index); a throwing stage drops that item to null.
- parallel(thunks): BARRIER — awaits all; a failed thunk folds to null. Use only when the next step genuinely needs ALL results together.
- log(message) / phase(title): progress narration and grouping.
- args: the tool call's args input, verbatim (pass real JSON values, not a stringified list).
- budget: spent() = output tokens this run; remaining() = Infinity (no token-target directive here).
- workflow(nameOrRef, args?): run a saved or scriptPath workflow inline (one nesting level only).
Unknown agent() options are rejected at the call. Subagents are told their final text IS the return value, so they return raw data.

Hard limits: concurrent agent() calls capped at min(16, CPUs-2) (excess queues); 1000 agents per run; 4096 items per parallel/pipeline call.

Pass the script inline via \`script\` (do not Write it to a file first); the result returns the persisted script path — iterate by editing that file and re-invoking with \`{scriptPath}\`. Scripts you run more than once belong in \`.pi/workflows/<name>.js\`; invoke with \`name\`. Resume after pause/kill/edit: re-invoke with \`{scriptPath, resumeFromRunId}\` — the longest unchanged prefix of agent() calls replays from cache; the first change and everything after runs live.

Use this tool for multi-step orchestration where control flow should be deterministic (loops, conditionals, fan-out) rather than model-driven.\`;`;;

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
ok = patchFile(RPC_SRC, DESC_TAIL_ANCHOR, DESC_TAIL_ANCHOR + DESC_SLIM_EXPORT, "slimWorkflowToolDescription", "slim-desc") && ok;
ok = patchFile(
	INDEX_SRC,
	"description: renderToolDescriptionTemplate(fullWorkflowToolDescription),",
	"description: renderToolDescriptionTemplate(slimWorkflowToolDescription),",
	"renderToolDescriptionTemplate(slimWorkflowToolDescription)",
	"slim-desc-wire",
) && ok;
if (!ok) process.exit(1);

const jitiCache = join(tmpdir(), "jiti");
try {
	rmSync(jitiCache, { recursive: true, force: true });
	console.log(`patch-subagents: 已清理 jiti 编译缓存 ${jitiCache}(pi 经 jiti 加载 src/*.ts,patch 后必须清缓存否则旧编译产物复活)`);
} catch (error) {
	console.error(`patch-subagents: jiti 缓存清理失败 ${String(error)}`);
	process.exit(1);
}
