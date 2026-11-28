import { register } from "node:module";
register(new URL("./typebox_shim.mjs", import.meta.url));
import { agentRow, headText, jobRow, journalLogWindow, listJobs, parseHandle, parseLogTail, pathDashEncode, scheduleRpc, storePath, taskRow, transcriptRow, transcriptWindow, validateSchedulePatch, workflowJournalDir, workflowJournalTail, workflowLogWindow, workflowRow, workflowStatusLines } from "../extensions/tasks.ts";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

const [root, scenario, payloadRaw] = process.argv.slice(2);
const p = JSON.parse(payloadRaw || "{}");
const out = {};

const CHANNELS = {
	ping: "subagents:rpc:ping",
	list: "subagents:rpc:list",
	get: "subagents:rpc:get",
	stop: "subagents:rpc:stop",
	workflow_list: "subagents:rpc:workflow_list",
	workflow_status: "subagents:rpc:workflow_status",
	workflow_stop: "subagents:rpc:workflow_stop",
	schedule_list: "subagents:rpc:schedule_list",
	schedule_remove: "subagents:rpc:schedule_remove",
	schedule_update: "subagents:rpc:schedule_update",
};
const DEFAULT_FEATURES = ["consume", "steer", "get", "list", "kit-schedule", "kit-workflow"];
const text = (result) => result.content?.[0]?.text ?? "";

function fakeEvents() {
	const handlers = new Map();
	return {
		on: (ch, h) => {
			const arr = handlers.get(ch) ?? [];
			arr.push(h);
			handlers.set(ch, arr);
			return () => {};
		},
		emit: (ch, data) => {
			for (const h of handlers.get(ch) ?? []) h(data);
		},
		registerUpstream: (channel, fn) => {
			handlers.set(channel, [
				(req) => {
					try {
						const data = fn(req);
						handlers.get(`${channel}:reply:${req.requestId}`)?.forEach((h) => h({ success: true, ...(data === undefined ? {} : { data }) }));
					} catch (error) {
						handlers.get(`${channel}:reply:${req.requestId}`)?.forEach((h) => h({ success: false, error: String(error.message ?? error) }));
					}
				},
			]);
		},
	};
}

async function bootFactory(p, root) {
	const { default: factory } = await import("../extensions/tasks.ts");
	const tools = {};
	const handlers = {};
	const sent = [];
	const events = fakeEvents();
	const armedAt = Date.now();
	for (const [name, behavior] of Object.entries(p.upstream ?? {})) {
		events.registerUpstream(CHANNELS[name] ?? name, () => {
			const value = behavior && typeof behavior === "object" && "flipAfterMs" in behavior ? (Date.now() - armedAt >= behavior.flipAfterMs ? behavior.then : behavior.data) : behavior;
			if (value && typeof value === "object" && "throw" in value) throw new Error(value.throw);
			return value;
		});
	}
	const features = p.features === undefined ? DEFAULT_FEATURES : p.features;
	if (features && !(p.upstream && "ping" in p.upstream)) {
		events.registerUpstream(CHANNELS.ping, () => ({ version: 2, features }));
	}
	let sessionFile;
	if (p.transcript) {
		sessionFile = join(root, "agent-session.jsonl");
		await writeFile(sessionFile, p.transcript.map((entry) => JSON.stringify(entry)).join("\n") + "\n", "utf8");
	}
	if (p.agents) {
		events.registerUpstream(CHANNELS.list, () => ({ agents: p.agents.map((agent) => ({ ...agent, ...(agent.sessionFile === "$transcript" ? { sessionFile } : {}) })) }));
	}
	let journalDir;
	if (p.journal) {
		journalDir = workflowJournalDir(root, p.sessionId ?? "sess-1");
		await mkdir(journalDir, { recursive: true });
		await writeFile(join(journalDir, "wf_test1234.workflow.jsonl"), p.journal.map((entry) => JSON.stringify(entry)).join("\n") + "\n", "utf8");
	}
	const pi = {
		on: (event, handler) => {
			handlers[event] = handler;
		},
		registerTool: (tool) => {
			tools[tool.name] = tool;
		},
		registerCommand: () => {},
		sendMessage: (message) => {
			sent.push(message.content);
		},
		events,
	};
	await factory(pi);
	const ctx = { cwd: root, sessionManager: { getBranch: () => [], getSessionId: () => p.sessionId ?? "sess-1" }, isIdle: () => true };
	await handlers["session_start"]({}, ctx);
	return { tools, handlers, sent, ctx, journalDir };
}

if (scenario === "format") {
	out.task = p.task ? taskRow({ exitCode: null, pid: 123, ...p.task }) : null;
	out.agent = p.agent ? agentRow({ startedAt: 0, durationMs: 5000, ...p.agent }) : null;
	out.workflow = p.workflow ? workflowRow({ doneCount: 0, agentCount: 0, replayedCount: 0, tokens: 0, ...p.workflow }) : null;
	out.statusLines = p.statusDetail ? workflowStatusLines(p.statusDetail) : null;
	out.job = p.job ? jobRow({ runCount: 0, ...p.job }) : null;
	out.handles = (p.handles ?? []).map((handle) => parseHandle(handle));
	out.transcript = (p.messages ?? []).map((message) => transcriptRow(message));
	out.head = headText(p.text ?? "", p.chars ?? 10);
	out.tail = parseLogTail(p.text ?? "", p.chars ?? 10);
} else if (scenario === "path") {
	out.path = storePath(p.cwd ?? "/w", p.sessionId ?? "s");
} else if (scenario === "validate") {
	out.error = validateSchedulePatch(p.patch);
} else if (scenario === "rpc") {
	const events = fakeEvents();
	if (p.mode === "ok") {
		events.registerUpstream(p.channel, (req) => ({ echo: req.jobId }));
	} else if (p.mode === "timeout") {
		p.channel = "subagents:rpc:nowhere";
	}
	out.reply = await scheduleRpc(events, p.channel, { jobId: p.jobId ?? "j1" }, p.timeoutMs ?? 300, () => "fixed-id");
} else if (scenario === "jobs") {
	const events = p.upstream ? fakeEvents() : undefined;
	if (events && p.upstream === "list") events.registerUpstream("subagents:rpc:schedule_list", () => [p.job ?? {}]);
	if (events && p.upstream === "throw") {
		events.registerUpstream("subagents:rpc:schedule_list", () => {
			throw new Error("scheduler not active");
		});
	}
	out.outcome = await listJobs(p.cwd ?? root, p.noSessionId ? undefined : p.sessionId ?? "sess-1", events);
} else if (scenario === "journal-tail") {
	const dir = join(root, "journal");
	if (p.fresh) await rm(dir, { recursive: true, force: true });
	if (p.makeFiles) {
		await mkdir(dir, { recursive: true });
		await writeFile(join(dir, `${p.runId ?? "wf_test1234"}.workflow.jsonl`), p.makeFiles.map((e) => JSON.stringify(e)).join("\n") + "\n", "utf8");
	}
	const tail = await workflowJournalTail(dir, p.runId ?? "wf_test1234", p.lines ?? 20);
	out.tail = tail ? { total: tail.total, okCount: tail.okCount, indexes: tail.tail.map((r) => r.index) } : null;
	out.badId = await workflowJournalTail(dir, "../../etc/passwd", 5);
	out.encode = pathDashEncode("/home/remedy/workspace/x y");
	out.dirOverride = workflowJournalDir("/any", undefined, root);
} else if (scenario === "log-windows") {
	out.journal = p.rows ? journalLogWindow({ total: p.total ?? 5, okCount: 1, tail: p.rows }, p.since) : null;
	out.workflow = workflowLogWindow(p.logs ?? [], p.logTotal ?? (p.logs ?? []).length, p.since);
} else if (scenario === "transcript-window") {
	const path = join(root, "session.jsonl");
	if (p.fresh) await rm(root, { recursive: true, force: true });
	await mkdir(root, { recursive: true });
	if (p.make) {
		await writeFile(path, p.make.map((entry) => JSON.stringify(entry)).join("\n") + (p.partial ? "" : "\n"), "utf8");
	}
	out.window = await transcriptWindow(path, p.since);
	out.missing = await transcriptWindow(join(root, "nope.jsonl"));
} else if (scenario === "tools") {
	const { tools, handlers, ctx, journalDir } = await bootFactory(p, root);
	out.results = [];
	for (const call of p.calls ?? []) {
		const tool = tools[call.tool];
		if (!tool) throw new Error(`tool not registered: ${call.tool}`);
		const result = await tool.execute("call-1", call.params ?? {}, undefined, undefined, ctx);
		out.results.push({ text: text(result), isError: result.isError === true, details: result.details });
	}
	out.names = Object.keys(tools).sort();
	await handlers["session_shutdown"]?.();
	if (journalDir) await rm(journalDir, { recursive: true, force: true });
} else {
	throw new Error(`unknown scenario: ${scenario}`);
}

console.log(JSON.stringify(out));
