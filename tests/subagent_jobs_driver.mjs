import { formatJobs, formatWorkflowRuns, formatWorkflowStatus, listJobs, registerWorkflowRunTools, scheduleRpc, storePath, validateSchedulePatch } from "../extensions/subagent-jobs.ts";

const [scenario, payload] = process.argv.slice(2);
const p = JSON.parse(payload || "{}");
const out = {};

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

const JOB = {
	id: "W6E5_nfAyQ",
	name: "每日晨报巡查agent",
	schedule: "2026-11-06T00:00:00.000Z",
	scheduleType: "once",
	enabled: true,
	runCount: 0,
	createdAt: "2026-11-05T01:20:57.300Z",
	nextRun: "2026-11-06T00:00:00.000Z",
};

if (scenario === "format") {
	out.text = formatJobs(p.jobs ?? [], p.source ?? "file");
} else if (scenario === "path") {
	out.path = storePath(p.cwd ?? "/w", p.sessionId ?? "s");
} else if (scenario === "validate") {
	out.error = validateSchedulePatch(p.patch);
} else if (scenario === "rpc") {
	const events = fakeEvents();
	if (p.upstream) {
		if (p.upstream === "list") {
			events.registerUpstream("subagents:rpc:schedule_list", () => [JOB]);
		} else if (p.upstream === "throw") {
			events.registerUpstream("subagents:rpc:schedule_list", () => {
				throw new Error("scheduler not active");
			});
		}
	}
	out.outcome = await listJobs(p.cwd, p.noSessionId ? undefined : p.sessionId ?? "sess-1", events);
} else if (scenario === "call") {
	const events = fakeEvents();
	if (p.mode === "ok") {
		events.registerUpstream(p.channel, (req) => ({ echo: req.jobId }));
	} else if (p.mode === "timeout") {
		p.channel = "subagents:rpc:nowhere";
	}
	out.reply = await scheduleRpc(events, p.channel, { jobId: p.jobId ?? "j1" }, p.timeoutMs ?? 300, () => "fixed-id");
}

if (scenario === "wf-format") {
	out.runsText = formatWorkflowRuns(p.runs ?? []);
	out.statusText = p.detail ? formatWorkflowStatus(p.detail) : null;
} else if (scenario === "wf-tools") {
	const tools = new Map();
	const pi = {
		events: fakeEvents(),
		registerTool: (tool) => tools.set(tool.name, tool),
	};
	const Type = {
		Object: (properties) => ({ type: "object", properties }),
		String: (description) => ({ type: "string", ...(description ? { description: description.description } : {}) }),
		Number: (description) => ({ type: "number", ...(description ? { description: description.description } : {}) }),
		Boolean: (description) => ({ type: "boolean", ...(description ? { description: description.description } : {}) }),
		Optional: (schema) => schema,
	};
	registerWorkflowRunTools(pi, Type);
	const upstream = p.upstream ?? {};
	for (const [channel, behavior] of Object.entries(upstream)) {
		pi.events.registerUpstream(channel, () => {
			if (behavior.throw) throw new Error(behavior.throw);
			return behavior.data;
		});
	}
	const tool = tools.get(p.tool);
	if (!tool) throw new Error(`tool not registered: ${p.tool}`);
	const result = await tool.execute("call-1", p.params ?? {}, undefined, undefined, { cwd: "/w", sessionManager: { getSessionId: () => "sess-1" } });
	out.result = { text: result.content?.[0]?.text ?? "", isError: result.isError === true };
}

console.log(JSON.stringify(out));
