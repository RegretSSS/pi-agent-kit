import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export type TodoStatus = "pending" | "in_progress" | "done";
export type TodoItem = { id: number; text: string; status: TodoStatus; doneAt?: number };
export type TodoSettle = { dropped: number[]; done: number; pending: number };
export type TodoOp =
	| { op: "add"; id: number; text: string; settled?: TodoSettle }
	| { op: "status"; id: number; status: TodoStatus; doneAt?: number; settled?: TodoSettle }
	| { op: "archive"; ids: number[]; settled?: TodoSettle }
	| { op: "clear" };
export type TodoState = { todos: TodoItem[]; nextId: number; settledDone: number; settledPending: number };
export type TodoDetails = { action: string; error?: string; done: number; open: number; total: number; activeId?: number; nextId: number; settled: number };
export type TodoParams = { action: string; text?: string; id?: number; status?: TodoStatus };
export type SessionEntry = { type: string; customType?: string; data?: unknown };

export const LEGACY_SNAPSHOT_ENTRY = "todo-state";
export const TODO_OP_ENTRY = "todo-op";
export const DONE_KEEP = 3;
export const PENDING_KEEP = 40;
export const TODO_LIST_KEEP = 40;
export const ROW_CHARS = 120;
const STATUSES: readonly string[] = ["pending", "in_progress", "done"];

export function emptyState(): TodoState {
	return { todos: [], nextId: 1, settledDone: 0, settledPending: 0 };
}

export function settle(todos: TodoItem[]): { todos: TodoItem[]; dropped: TodoItem[] } {
	const done = todos.filter((t) => t.status === "done").sort((a, b) => (a.doneAt ?? 0) - (b.doneAt ?? 0));
	const pending = todos.filter((t) => t.status === "pending");
	const stale = new Set([...done.slice(0, -DONE_KEEP), ...pending.slice(0, -PENDING_KEEP)].map((t) => t.id));
	return { todos: todos.filter((t) => !stale.has(t.id)), dropped: todos.filter((t) => stale.has(t.id)) };
}

function settleInfo(dropped: TodoItem[]): TodoSettle {
	return {
		dropped: dropped.map((t) => t.id),
		done: dropped.filter((t) => t.status === "done").length,
		pending: dropped.filter((t) => t.status === "pending").length,
	};
}

export function withStatus(todos: TodoItem[], id: number, status: TodoStatus, doneAt: number | undefined): TodoItem[] {
	if (!todos.some((t) => t.id === id)) return todos;
	return todos.map((t) => {
		if (t.id === id) return { ...t, status, doneAt };
		if (status === "in_progress" && t.status === "in_progress") return { ...t, status: "pending" };
		return t;
	});
}

function applyChange(state: TodoState, op: TodoOp): TodoState {
	switch (op.op) {
		case "add":
			return { todos: [...state.todos, { id: op.id, text: op.text, status: "pending" }], nextId: Math.max(state.nextId, op.id + 1), settledDone: state.settledDone, settledPending: state.settledPending };
		case "status":
			return { ...state, todos: withStatus(state.todos, op.id, op.status, op.doneAt) };
		case "archive": {
			const archived = new Set(op.ids);
			return { ...state, todos: state.todos.filter((t) => !archived.has(t.id)) };
		}
		case "clear":
			return emptyState();
	}
}

export function applyOp(state: TodoState, op: TodoOp): TodoState {
	const changed = applyChange(state, op);
	const settled = "settled" in op ? op.settled : undefined;
	if (!settled) return changed;
	const dropped = new Set(settled.dropped);
	return {
		todos: changed.todos.filter((t) => !dropped.has(t.id)),
		nextId: changed.nextId,
		settledDone: changed.settledDone + settled.done,
		settledPending: changed.settledPending + settled.pending,
	};
}

function withSettle(state: TodoState, op: TodoOp): TodoOp {
	const { dropped } = settle(applyChange(state, op).todos);
	if (dropped.length === 0 || op.op === "clear") return op;
	return { ...op, settled: settleInfo(dropped) };
}

function isStatus(value: unknown): value is TodoStatus {
	return typeof value === "string" && STATUSES.includes(value);
}

function parseSettle(value: unknown): TodoSettle {
	if (value === null || typeof value !== "object") return { dropped: [], done: 0, pending: 0 };
	const { dropped, done, pending } = value as { dropped?: unknown; done?: unknown; pending?: unknown };
	return {
		dropped: Array.isArray(dropped) ? dropped.filter((id): id is number => typeof id === "number") : [],
		done: typeof done === "number" ? done : 0,
		pending: typeof pending === "number" ? pending : 0,
	};
}

export function parseOp(data: unknown): TodoOp | null {
	if (data === null || typeof data !== "object") return null;
	const { op, id, text, status, doneAt, ids, settled } = data as Record<string, unknown>;
	const extra = () => (settled === undefined ? {} : { settled: parseSettle(settled) });
	if (op === "add" && typeof id === "number" && typeof text === "string") return { op, id, text, ...extra() };
	if (op === "status" && typeof id === "number" && isStatus(status)) return { op, id, status, ...(typeof doneAt === "number" ? { doneAt } : {}), ...extra() };
	if (op === "archive" && Array.isArray(ids)) {
		const numbers = ids.filter((item): item is number => typeof item === "number");
		return numbers.length === ids.length ? { op, ids: numbers, ...extra() } : null;
	}
	if (op === "clear") return { op };
	return null;
}

function fromSnapshot(data: unknown): TodoState {
	const snapshot = (data ?? {}) as Partial<TodoState>;
	return {
		todos: snapshot.todos ?? [],
		nextId: typeof snapshot.nextId === "number" ? snapshot.nextId : 1,
		settledDone: snapshot.settledDone ?? 0,
		settledPending: snapshot.settledPending ?? 0,
	};
}

export function reconstructTodos(branch: SessionEntry[]): TodoState {
	let state = emptyState();
	for (const entry of branch) {
		if (entry.type !== "custom") continue;
		if (entry.customType === LEGACY_SNAPSHOT_ENTRY) {
			if (Array.isArray((entry.data as Partial<TodoState> | null)?.todos)) state = fromSnapshot(entry.data);
		} else if (entry.customType === TODO_OP_ENTRY) {
			const op = parseOp(entry.data);
			if (op) state = applyOp(state, op);
		}
	}
	return state;
}

function rowText(text: string): string {
	const flat = text.replace(/\s+/g, " ").trim();
	const points = Array.from(flat);
	return points.length > ROW_CHARS ? `${points.slice(0, ROW_CHARS - 1).join("")}…` : flat;
}

export function formatTodos(todos: TodoItem[], cap: number = TODO_LIST_KEEP, settledDone = 0): string {
	if (todos.length === 0) return "无条目";
	const done = todos.filter((t) => t.status === "done").length + settledDone;
	const open = todos.filter((t) => t.status !== "done").length;
	const priority = todos.filter((t) => t.status !== "pending");
	const pending = todos.filter((t) => t.status === "pending");
	const shown = [...priority, ...pending].slice(0, cap);
	const rows = shown.map((t) => {
		const mark = t.status === "done" ? "x" : t.status === "in_progress" ? ">" : " ";
		return `[${mark}] #${t.id}: ${rowText(t.text)}`;
	});
	const hidden = todos.length - shown.length;
	const tail = hidden > 0 ? [`…另有 ${hidden} 条未显示: todo full 看全量 / todo archive 清挂账`] : [];
	return [`已完成 ${done} · 未完成 ${open}`, ...rows, ...tail].join("\n");
}

export function detailsOf(state: TodoState, action: string, error?: string): TodoDetails {
	const active = state.todos.find((t) => t.status === "in_progress");
	const details: TodoDetails = {
		action,
		done: state.todos.filter((t) => t.status === "done").length + state.settledDone,
		open: state.todos.filter((t) => t.status !== "done").length,
		total: state.todos.length,
		activeId: active?.id,
		nextId: state.nextId,
		settled: state.settledPending,
	};
	if (error) details.error = error;
	return details;
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	const { StringEnum } = await import("@earendil-works/pi-ai");
	const { Text } = await import("@earendil-works/pi-tui");
	let state = emptyState();

	const rebuild = (ctx: ExtensionContext) => {
		state = reconstructTodos(ctx.sessionManager.getBranch() as never);
	};

	const summarize = (action: string, error?: string): TodoDetails => detailsOf(state, action, error);

	pi.on("session_start", async (_event, ctx) => rebuild(ctx));
	pi.on("session_tree", async (_event, ctx) => rebuild(ctx));

	pi.registerTool({
		name: "todo",
		label: "Todo",
		description: "计划待办清单。每条是一个能被标 done 的具体动作——不是日志、交接摘要或状态快照(那些写进文件或 memory)。多步任务动手前建单;开工一步前标 in_progress(同时刻仅一个,设置新的会自动把旧的退回 pending);完成即 done。活动清单自动保持干净:done 只留最近 3 条,pending 只留最近 40 条,更旧的自动沉降(全史在本会话 jsonl 的 todo 条目里);list 默认最多 40 行;挂账候裁的 pending 批量用 archive 清出。行动: list / full / add(text) / status(id,status) / toggle(id) / archive([id]) / clear。",
		promptSnippet: "计划待办清单",
		promptGuidelines: [
			"Break multi-step work into todo items before starting; keep exactly one item in_progress while executing; mark done immediately after completion; archive parked pending batches instead of letting them pile up.",
			"Never use todo items as journal entries, handoff notes or status snapshots: an item that can never be marked done does not belong here.",
		],
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
			const commit = (action: string, op: TodoOp, message: string): { content: { type: "text"; text: string }[]; details: TodoDetails } => {
				const entry = withSettle(state, op);
				try {
					pi.appendEntry(TODO_OP_ENTRY, entry);
				} catch (error) {
					return fail(`状态落盘失败: ${error instanceof Error ? error.message : String(error)}`);
				}
				state = applyOp(state, entry);
				const settled = "settled" in entry ? entry.settled : undefined;
				const note = settled?.pending ? `;最旧的 ${settled.pending} 条 pending 已沉降(活动清单只留最近 ${PENDING_KEEP} 条)` : "";
				return { content: [{ type: "text", text: `${message}${note}` }], details: summarize(action) };
			};
			switch (params.action) {
				case "list":
					return { content: [{ type: "text", text: formatTodos(state.todos, TODO_LIST_KEEP, state.settledDone) }], details: summarize("list") };
				case "full":
					return { content: [{ type: "text", text: formatTodos(state.todos, Number.POSITIVE_INFINITY, state.settledDone) }], details: summarize("full") };
				case "add": {
					if (typeof params.text !== "string" || params.text === "") return fail("add 需要 text");
					const id = state.nextId;
					return commit("add", { op: "add", id, text: params.text }, `已加 #${id}: ${rowText(params.text)}`);
				}
				case "status": {
					if (params.id === undefined || !isStatus(params.status)) return fail("status 需要 id 与 status");
					if (!state.todos.some((t) => t.id === params.id)) return fail(`#${params.id} 不存在`);
					return commit("status", { op: "status", id: params.id, status: params.status, doneAt: params.status === "done" ? Date.now() : undefined }, `#${params.id} → ${params.status}`);
				}
				case "toggle": {
					if (params.id === undefined) return fail("toggle 需要 id");
					const target = state.todos.find((t) => t.id === params.id);
					if (!target) return fail(`#${params.id} 不存在`);
					const next = target.status === "done" ? "pending" : "done";
					return commit("toggle", { op: "status", id: params.id, status: next, doneAt: next === "done" ? Date.now() : undefined }, `#${params.id} → ${next}`);
				}
				case "archive": {
					if (params.id !== undefined) {
						const target = state.todos.find((t) => t.id === params.id);
						if (!target) return fail(`#${params.id} 不存在`);
						if (target.status === "in_progress") return fail(`#${params.id} 是进行中锚点,先转状态再归档`);
						return commit("archive", { op: "archive", ids: [params.id] }, `已归档 #${params.id}(全史在本会话 jsonl 的 todo 条目里)`);
					}
					const droppable = state.todos.filter((t) => t.status !== "in_progress");
					if (droppable.length === 0) return fail("无可归档条目(仅剩进行中锚点或空)");
					return commit("archive", { op: "archive", ids: droppable.map((t) => t.id) }, `已归档 ${droppable.length} 条(全史在本会话 jsonl 的 todo 条目里)`);
				}
				case "clear": {
					const count = state.todos.length;
					return commit("clear", { op: "clear" }, `已清空 ${count} 条`);
				}
			}
			return fail(`未知 action: ${params.action}`);
		},
		renderCall(rawArgs, theme) {
			const args = rawArgs as TodoParams;
			let text = theme.fg("toolTitle", theme.bold("todo ")) + theme.fg("muted", args.action);
			if (args.text) text += ` ${theme.fg("dim", `"${rowText(args.text)}"`)}`;
			if (args.id !== undefined) text += ` ${theme.fg("accent", `#${args.id}`)}`;
			return new Text(text, 0, 0);
		},
		renderResult(result, _options, theme) {
			const details = result.details as TodoDetails | undefined;
			if (details?.error) return new Text(theme.fg("error", `Error: ${details.error}`), 0, 0);
			const summary = `已完成 ${details?.done ?? 0} · 未完成 ${details?.open ?? details?.total ?? 0}` + (details?.activeId !== undefined ? ` · 进行中 #${details.activeId}` : "");
			return new Text(theme.fg("muted", summary), 0, 0);
		},
	});

	pi.registerCommand("todos", {
		description: "显示当前分支的计划步骤清单",
		handler: async (_args, ctx) => {
			ctx.ui.notify(formatTodos(state.todos, TODO_LIST_KEEP, state.settledDone), "info");
		},
	});
}
