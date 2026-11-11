import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export type TodoStatus = "pending" | "in_progress" | "done";
export type TodoItem = { id: number; text: string; status: TodoStatus };
export type TodoDetails = { action: string; todos: TodoItem[]; nextId: number; error?: string };

export function markStatus(todos: TodoItem[], id: number, status: TodoStatus): TodoItem[] {
	const target = todos.find((t) => t.id === id);
	if (!target) return todos;
	const next = todos.map((t) => ({ ...t }));
	const hit = next.find((t) => t.id === id);
	hit.status = status;
	if (status === "in_progress") {
		for (const t of next) {
			if (t.id !== id && t.status === "in_progress") t.status = "pending";
		}
	}
	return next;
}

const TODO_LINE_RE = /^\[([ x>])] #(\d+): (.+?)(?: ← 进行中)?$/;

export function parseTodos(text: string): TodoItem[] | null {
	const items: TodoItem[] = [];
	for (const line of text.split("\n")) {
		const hit = TODO_LINE_RE.exec(line.trim());
		if (!hit) continue;
		const status = hit[1] === "x" ? "done" : hit[1] === ">" ? "in_progress" : "pending";
		items.push({ id: Number(hit[2]), text: hit[3], status });
	}
	if (items.length === 0) return null;
	return items;
}

function contentText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content.filter((b) => b && typeof b === "object" && (b as { type?: string }).type === "text").map((b) => (b as { text?: string }).text ?? "").join("\n");
}

export function reconstructTodos(branch: { type: string; message?: { role?: string; toolName?: string; details?: unknown; content?: unknown } }[]): { todos: TodoItem[]; nextId: number } {
	let todos: TodoItem[] = [];
	let nextId = 1;
	for (const entry of branch) {
		if (entry.type !== "message") continue;
		const msg = entry.message;
		if (!msg || msg.role !== "toolResult" || msg.toolName !== "todo") continue;
		const details = msg.details as TodoDetails | undefined;
		if (details && details.todos) {
			todos = details.todos;
			nextId = details.nextId;
			continue;
		}
		const parsed = parseTodos(contentText(msg.content));
		if (parsed) {
			todos = parsed;
			nextId = Math.max(...parsed.map((t) => t.id)) + 1;
		}
	}
	return { todos, nextId };
}

export function formatTodos(todos: TodoItem[]): string {
	if (todos.length === 0) return "无条目";
	const done = todos.filter((t) => t.status === "done").length;
	const head = `${done}/${todos.length} 完成`;
	const rows = todos.map((t) => {
		const mark = t.status === "done" ? "x" : t.status === "in_progress" ? ">" : " ";
		return `[${mark}] #${t.id}: ${t.text}${t.status === "in_progress" ? " ← 进行中" : ""}`;
	});
	return [head, ...rows].join("\n");
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	const { StringEnum } = await import("@earendil-works/pi-ai");
	const { Text } = await import("@earendil-works/pi-tui");
	let todos: TodoItem[] = [];
	let nextId = 1;

	const rebuild = (ctx: ExtensionContext) => {
		const state = reconstructTodos(ctx.sessionManager.getBranch() as never);
		todos = state.todos;
		nextId = state.nextId;
	};

	pi.on("session_start", async (_event, ctx) => rebuild(ctx));
	pi.on("session_tree", async (_event, ctx) => rebuild(ctx));

	pi.registerTool({
		name: "todo",
		label: "Todo",
		description: "计划步骤清单(会话分支感知,branch 后状态自动回放)。多步任务动手前先建单;开工一步前把它标 in_progress(同时刻仅一个,设置新的会自动把旧的退回 pending);完成即 done。行动: list / add(text) / status(id,status) / toggle(id) / clear。",
		promptSnippet: "计划步骤清单",
		promptGuidelines: ["Break multi-step work into todo items before starting; keep exactly one item in_progress while executing; mark done immediately after completion."],
		parameters: Type.Object({
			action: StringEnum(["list", "add", "status", "toggle", "clear"] as const),
			text: Type.Optional(Type.String({ description: "add 的条目文本" })),
			id: Type.Optional(Type.Integer({ description: "status/toggle 的目标条目 id" })),
			status: Type.Optional(StringEnum(["pending", "in_progress", "done"] as const, { description: "status 动作的目标状态" })),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
			const fail = (error: string): { content: { type: "text"; text: string }[]; details: TodoDetails } => ({
				content: [{ type: "text", text: `Error: ${error}` }],
				details: { action: params.action, todos: [...todos], nextId, error },
			});
			switch (params.action) {
				case "list":
					return { content: [{ type: "text", text: formatTodos(todos) }], details: { action: "list", todos: [...todos], nextId } };
				case "add": {
					if (!params.text) return fail("add 需要 text");
					const item: TodoItem = { id: nextId++, text: params.text, status: "pending" };
					todos = [...todos, item];
					return { content: [{ type: "text", text: `已加 #${item.id}: ${item.text}` }], details: { action: "add", todos: [...todos], nextId } };
				}
				case "status": {
					if (params.id === undefined || !params.status) return fail("status 需要 id 与 status");
					if (!todos.some((t) => t.id === params.id)) return fail(`#${params.id} 不存在`);
					todos = markStatus(todos, params.id, params.status);
					return { content: [{ type: "text", text: formatTodos(todos) }], details: { action: "status", todos: [...todos], nextId } };
				}
				case "toggle": {
					if (params.id === undefined) return fail("toggle 需要 id");
					const target = todos.find((t) => t.id === params.id);
					if (!target) return fail(`#${params.id} 不存在`);
					todos = markStatus(todos, params.id, target.status === "done" ? "pending" : "done");
					return { content: [{ type: "text", text: formatTodos(todos) }], details: { action: "toggle", todos: [...todos], nextId } };
				}
				case "clear": {
					const count = todos.length;
					todos = [];
					nextId = 1;
					return { content: [{ type: "text", text: `已清空 ${count} 条` }], details: { action: "clear", todos: [], nextId: 1 } };
				}
			}
		},
		renderCall(args, theme) {
			let text = theme.fg("toolTitle", theme.bold("todo ")) + theme.fg("muted", args.action);
			if (args.text) text += ` ${theme.fg("dim", `"${args.text}"`)}`;
			if (args.id !== undefined) text += ` ${theme.fg("accent", `#${args.id}`)}`;
			return new Text(text, 0, 0);
		},
		renderResult(result, theme) {
			const details = result.details as TodoDetails | undefined;
			if (details?.error) return new Text(theme.fg("error", `Error: ${details.error}`), 0, 0);
			const done = details ? details.todos.filter((t) => t.status === "done").length : 0;
			const total = details?.todos.length ?? 0;
			const active = details?.todos.find((t) => t.status === "in_progress");
			const summary = `${done}/${total} 完成` + (active ? ` · 进行中 #${active.id}` : "");
			return new Text(theme.fg("muted", summary), 0, 0);
		},
	});

	pi.registerCommand("todos", {
		description: "显示当前分支的计划步骤清单",
		handler: async (_args, ctx) => {
			ctx.ui.notify(formatTodos(todos), "info");
		},
	});
}
