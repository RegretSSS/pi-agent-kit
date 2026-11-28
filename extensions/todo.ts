import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export type TodoStatus = "pending" | "in_progress" | "done";
export type TodoItem = { id: number; text: string; status: TodoStatus; doneAt?: number };
export type TodoState = { todos: TodoItem[]; nextId: number };
export type TodoDetails = { action: string; error?: string; done: number; total: number; activeId?: number; nextId: number };
export type TodoParams = { action: string; text?: string; id?: number; status?: TodoStatus };

export const TODO_STATE_ENTRY = "todo-state";
export const DONE_KEEP = 3;
export const TODO_LIST_KEEP = 40;

export function settleDone(todos: TodoItem[]): TodoItem[] {
	const done = todos.filter((t) => t.status === "done").sort((a, b) => (a.doneAt ?? 0) - (b.doneAt ?? 0));
	const drop = new Set(done.slice(0, Math.max(0, done.length - DONE_KEEP)).map((t) => t.id));
	return todos.filter((t) => !drop.has(t.id));
}

export function markStatus(todos: TodoItem[], id: number, status: TodoStatus): TodoItem[] {
	if (!todos.some((t) => t.id === id)) return todos;
	return todos.map((t) => {
		if (t.id === id) return { ...t, status, doneAt: status === "done" ? Date.now() : undefined };
		if (status === "in_progress" && t.status === "in_progress") return { ...t, status: "pending" };
		return { ...t };
	});
}

export function reconstructTodos(branch: { type: string; customType?: string; data?: unknown }[]): TodoState {
	let state: TodoState = { todos: [], nextId: 1 };
	for (const entry of branch) {
		if (entry.type !== "custom" || entry.customType !== TODO_STATE_ENTRY) continue;
		const data = entry.data as TodoState | undefined;
		if (data && Array.isArray(data.todos)) state = { todos: data.todos, nextId: data.nextId };
	}
	return state;
}

export function formatTodos(todos: TodoItem[], cap: number = TODO_LIST_KEEP): string {
	if (todos.length === 0) return "无条目";
	const done = todos.filter((t) => t.status === "done").length;
	const head = `${done}/${todos.length} 完成`;
	const priority = todos.filter((t) => t.status !== "pending");
	const pending = todos.filter((t) => t.status === "pending");
	const shown = [...priority, ...pending].slice(0, cap);
	const rows = shown.map((t) => {
		const mark = t.status === "done" ? "x" : t.status === "in_progress" ? ">" : " ";
		return `[${mark}] #${t.id}: ${t.text}`;
	});
	const hidden = todos.length - shown.length;
	const tail = hidden > 0 ? [`…另有 ${hidden} 条未显示: todo full 看全量 / todo archive 清挂账`] : [];
	return [head, ...rows, ...tail].join("\n");
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

	const summarize = (action: string, error?: string): TodoDetails => {
		const active = todos.find((t) => t.status === "in_progress");
		const details: TodoDetails = {
			action,
			done: todos.filter((t) => t.status === "done").length,
			total: todos.length,
			activeId: active?.id,
			nextId,
		};
		if (error) details.error = error;
		return details;
	};

	pi.on("session_start", async (_event, ctx) => rebuild(ctx));
	pi.on("session_tree", async (_event, ctx) => rebuild(ctx));

	pi.registerTool({
		name: "todo",
		label: "Todo",
		description: "计划步骤清单(状态经 custom entry 持久化,重启/branch/compact 后自动回放)。多步任务动手前先建单;开工一步前把它标 in_progress(同时刻仅一个,设置新的会自动把旧的退回 pending);完成即 done。已完条目只保留最近 3 条,更早的自动沉降;list 默认最多 40 行(非 pending 优先,超出提示 todo full/archive);挂账候裁的 pending 批量用 archive 清出活动视图——沉降与归档的全史都在本会话 jsonl 的 todo-state 条目里,跨会话历史在 ~/.pi/agent/sessions/ 下 grep todo-state 可回。行动: list / full / add(text) / status(id,status) / toggle(id) / archive([id]) / clear。",
		promptSnippet: "计划步骤清单",
		promptGuidelines: ["Break multi-step work into todo items before starting; keep exactly one item in_progress while executing; mark done immediately after completion; archive parked pending batches instead of letting them pile up."],
		parameters: Type.Object({
			action: StringEnum(["list", "full", "add", "status", "toggle", "archive", "clear"] as const),
			text: Type.Optional(Type.String({ description: "add 的条目文本" })),
			id: Type.Optional(Type.Integer({ description: "status/toggle/archive 的目标条目 id" })),
			status: Type.Optional(StringEnum(["pending", "in_progress", "done"] as const, { description: "status 动作的目标状态" })),
		}),
		async execute(_toolCallId, rawParams, _signal, _onUpdate, ctx) {
			const params = rawParams as TodoParams;
			const fail = (error: string): { content: { type: "text"; text: string }[]; details: TodoDetails } => ({
				content: [{ type: "text", text: `Error: ${error}` }],
				details: summarize(params.action, error),
			});
			const commit = (action: string, message: string): { content: { type: "text"; text: string }[]; details: TodoDetails } => {
				todos = settleDone(todos);
				try {
					pi.appendEntry(TODO_STATE_ENTRY, { todos, nextId });
				} catch (error) {
					return fail(`状态落盘失败: ${error instanceof Error ? error.message : String(error)}`);
				}
				return { content: [{ type: "text", text: message }], details: summarize(action) };
			};
			switch (params.action) {
				case "list":
					return { content: [{ type: "text", text: formatTodos(todos) }], details: summarize("list") };
				case "full":
					return { content: [{ type: "text", text: formatTodos(todos, Number.POSITIVE_INFINITY) }], details: summarize("full") };
				case "add": {
					if (!params.text) return fail("add 需要 text");
					const item: TodoItem = { id: nextId++, text: params.text, status: "pending" };
					todos = [...todos, item];
					return commit("add", `已加 #${item.id}: ${item.text}`);
				}
				case "status": {
					if (params.id === undefined || !params.status) return fail("status 需要 id 与 status");
					if (!todos.some((t) => t.id === params.id)) return fail(`#${params.id} 不存在`);
					todos = markStatus(todos, params.id, params.status);
					return commit("status", `#${params.id} → ${params.status}`);
				}
				case "toggle": {
					if (params.id === undefined) return fail("toggle 需要 id");
					const target = todos.find((t) => t.id === params.id);
					if (!target) return fail(`#${params.id} 不存在`);
					const next = target.status === "done" ? "pending" : "done";
					todos = markStatus(todos, params.id, next);
					return commit("toggle", `#${params.id} → ${next}`);
				}
				case "archive": {
					if (params.id !== undefined) {
						const target = todos.find((t) => t.id === params.id);
						if (!target) return fail(`#${params.id} 不存在`);
						if (target.status === "in_progress") return fail(`#${params.id} 是进行中锚点,先转状态再归档`);
						todos = todos.filter((t) => t.id !== params.id);
						return commit("archive", `已归档 #${params.id}(全史在本会话 jsonl 的 todo-state)`);
					}
					const dropped = todos.filter((t) => t.status !== "in_progress");
					if (dropped.length === 0) return fail("无可归档条目(仅剩进行中锚点或空)");
					todos = todos.filter((t) => t.status === "in_progress");
					return commit("archive", `已归档 ${dropped.length} 条(全史在本会话 jsonl 的 todo-state)`);
				}
				case "clear": {
					const count = todos.length;
					todos = [];
					nextId = 1;
					return commit("clear", `已清空 ${count} 条`);
				}
			}
			return fail(`未知 action: ${params.action}`);
		},
		renderCall(rawArgs, theme) {
			const args = rawArgs as TodoParams;
			let text = theme.fg("toolTitle", theme.bold("todo ")) + theme.fg("muted", args.action);
			if (args.text) text += ` ${theme.fg("dim", `"${args.text}"`)}`;
			if (args.id !== undefined) text += ` ${theme.fg("accent", `#${args.id}`)}`;
			return new Text(text, 0, 0);
		},
		renderResult(result, _options, theme) {
			const details = result.details as TodoDetails | undefined;
			if (details?.error) return new Text(theme.fg("error", `Error: ${details.error}`), 0, 0);
			const summary = `${details?.done ?? 0}/${details?.total ?? 0} 完成` + (details?.activeId !== undefined ? ` · 进行中 #${details.activeId}` : "");
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
