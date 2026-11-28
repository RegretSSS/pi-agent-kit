import { readFileSync } from "node:fs";
import { register } from "node:module";
register(new URL("./typebox_shim.mjs", import.meta.url));
const { default: factory, withStatus, reconstructTodos, formatTodos, settle, detailsOf, TODO_LIST_KEEP } = await import("../extensions/todo.ts");

const [scenario, payloadRaw] = process.argv.slice(2);
const payload = payloadRaw === "-" ? JSON.parse(readFileSync(0, "utf8")) : payloadRaw ? JSON.parse(payloadRaw) : {};
const out = {};

if (scenario === "settle") {
	out.settled = settle(payload.todos ?? []);
} else if (scenario === "mark-status") {
	out.todos = withStatus(payload.todos, payload.id, payload.status, payload.status === "done" ? 1 : undefined);
} else if (scenario === "reconstruct") {
	out.state = reconstructTodos(payload.branch ?? []);
} else if (scenario === "format") {
	out.text = formatTodos(payload.todos ?? [], typeof payload.cap === "number" ? payload.cap : undefined, typeof payload.settledDone === "number" ? payload.settledDone : undefined);
} else if (scenario === "session") {
	const handlers = {};
	const tools = {};
	const commands = {};
	const entries = [];
	let appends = 0;
	const pi = {
		on: (event, handler) => {
			handlers[event] = handler;
		},
		registerTool: (tool) => {
			tools[tool.name] = tool;
		},
		registerCommand: (name, def) => {
			commands[name] = def;
		},
		appendEntry: (customType, data) => {
			appends += 1;
			if (payload.appendFails || appends <= (payload.appendFailCount ?? 0)) throw new Error("mock append reject");
			entries.push({ type: "custom", customType, data });
		},
	};
	await factory(pi);
	const ctx = {
		sessionManager: {
			getBranch: () => payload.branch ?? [],
		},
	};
	if (handlers["session_start"]) await handlers["session_start"]({}, ctx);
	for (const step of payload.steps ?? []) {
		const result = await tools.todo.execute("t1", step, undefined, undefined, ctx);
		out.steps = out.steps ?? [];
		out.steps.push({
			text: result.content[0].text,
			error: result.details.error ?? null,
			done: result.details.done,
			open: result.details.open,
			total: result.details.total,
			settled: result.details.settled,
			activeId: result.details.activeId ?? null,
			nextId: result.details.nextId,
		});
	}
	out.branch = entries;
	const replayed = reconstructTodos([...(payload.branch ?? []), ...entries]);
	out.replayed = replayed;
	out.replayedDetails = detailsOf(replayed, "replay");
	out.replayedText = formatTodos(replayed.todos, TODO_LIST_KEEP, replayed.settledDone);
	out.replayedFull = formatTodos(replayed.todos, Number.POSITIVE_INFINITY, replayed.settledDone);
	out.command = commands["todos"] ? await (async () => {
		const notes = [];
		await commands["todos"].handler([], { ui: { notify: (text) => notes.push(text) } });
		return notes;
	})() : null;
} else if (scenario === "render") {
	const tool = {};
	await factory({ on: () => {}, registerTool: (t) => { tool.todo = t; }, registerCommand: () => {}, appendEntry: () => {} });
	const theme = { fg: (_color, text) => `[${text}]`, bold: (text) => text };
	const options = { expanded: false, isPartial: false };
	out.call = tool.todo.renderCall(payload.args ?? {}, theme, {}).text;
	out.result = tool.todo.renderResult({ content: [], details: payload.details }, options, theme, {}).text;
} else {
	throw new Error(`unknown scenario: ${scenario}`);
}

console.log(JSON.stringify(out));
