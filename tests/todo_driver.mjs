import { register } from "node:module";
register(new URL("./typebox_shim.mjs", import.meta.url));
const { default: factory, markStatus, reconstructTodos, formatTodos } = await import("../extensions/todo.ts");

const [scenario, payloadRaw] = process.argv.slice(2);
const payload = payloadRaw ? JSON.parse(payloadRaw) : {};
const out = {};

if (scenario === "mark-status") {
	out.todos = markStatus(payload.todos, payload.id, payload.status);
} else if (scenario === "reconstruct") {
	out.state = reconstructTodos(payload.branch ?? []);
} else if (scenario === "format") {
	out.text = formatTodos(payload.todos ?? []);
} else if (scenario === "session") {
	const handlers = {};
	const tools = {};
	const commands = {};
	const entries = [];
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
			if (payload.appendFails) throw new Error("mock append reject");
			entries.push({ customType, data });
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
		out.steps.push({ text: result.content[0].text, todos: result.details.todos.map((t) => [String(t.id), t.status]), error: result.details.error ?? null });
	}
	out.entries = entries.filter((e) => e.customType === "todo-state").map((e) => e.data);
	out.command = commands["todos"] ? await (async () => {
		const notes = [];
		await commands["todos"].handler([], { ui: { notify: (text) => notes.push(text) } });
		return notes;
	})() : null;
} else {
	throw new Error(`unknown scenario: ${scenario}`);
}

console.log(JSON.stringify(out));
