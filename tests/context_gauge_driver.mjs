import factory, { gaugeLine } from "../extensions/context-gauge.ts";

const [scenario, payload] = process.argv.slice(2);
const p = JSON.parse(payload || "{}");
const out = {};

if (scenario === "line") {
	out.line = gaugeLine(p.tokens, p.contextWindow);
} else if (scenario === "attach") {
	const handlers = {};
	const statuses = [];
	const pi = {
		on: (event, handler) => {
			handlers[event] = handler;
		},
	};
	await factory(pi);
	const results = [];
	let turn = 0;
	for (const step of p.steps) {
		if (step.turnStart) {
			turn += 1;
			await handlers["turn_start"]?.({ type: "turn_start", turnIndex: turn, timestamp: 0 });
			continue;
		}
		if (step.compact) {
			await handlers["session_compact"]?.({ type: "session_compact", reason: "manual" });
			continue;
		}
		if (step.turnEnd) {
			await handlers["turn_end"]({ type: "turn_end", turnIndex: turn, timestamp: 0 }, step.ctx ?? { hasUI: false });
			continue;
		}
		const ctx = {
			hasUI: step.hasUI ?? false,
			getContextUsage: () =>
				step.usage === null ? undefined : { tokens: step.usage.tokens, contextWindow: step.usage.window, percent: step.usage.percent ?? null },
			ui: { setStatus: (_key, value) => statuses.push(value) },
		};
		const event = {
			isError: step.isError ?? false,
			content: step.content ?? [{ type: "text", text: "tool output" }],
			structuredContent: step.structuredContent,
		};
		const result = await handlers["tool_result"](event, ctx);
		results.push({
			appended: result ? result.content[result.content.length - 1].text : null,
			original: result ? result.content[0].text : null,
			structuredContent: result?.structuredContent ?? null,
		});
	}
	out.results = results;
	out.statuses = statuses;
}

console.log(JSON.stringify(out));
