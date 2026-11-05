import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export type StoredJob = {
	id: string;
	name: string;
	schedule: string;
	scheduleType: string;
	enabled: boolean;
	runCount: number;
	createdAt: string;
	nextRun?: string;
	lastRun?: string;
	lastStatus?: string;
};

export type JobListOutcome =
	| { status: "ok"; text: string; jobs: Array<Pick<StoredJob, "id" | "name" | "enabled" | "scheduleType" | "schedule" | "nextRun">>; source: "rpc" | "file" }
	| { status: "no-session" }
	| { status: "no-store" }
	| { status: "unreadable"; message: string };

export type EventBusLike = {
	on(event: string, handler: (data: unknown) => void): () => void;
	emit(event: string, data: unknown): void;
};

export type RpcReply<T> = { success: true; data?: T } | { success: false; error: string };

export function scheduleRpc<T>(events: EventBusLike, channel: string, params: Record<string, unknown>, timeoutMs = 5000, genId: () => string = defaultRequestId): Promise<RpcReply<T>> {
	return new Promise((resolve) => {
		const requestId = genId();
		const replyChannel = `${channel}:reply:${requestId}`;
		let done = false;
		const unsub = events.on(replyChannel, (reply) => {
			if (done) return;
			done = true;
			clearTimeout(timer);
			unsub();
			resolve(reply as RpcReply<T>);
		});
		const timer = setTimeout(() => {
			if (done) return;
			done = true;
			unsub();
			resolve({ success: false, error: `rpc timeout: ${channel}(pi-subagents 未打 schedule-rpc patch 或 scheduler 未激活)` });
		}, timeoutMs);
		events.emit(channel, { requestId, ...params });
	});
}

function defaultRequestId(): string {
	return `kit-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function storePath(cwd: string, sessionId: string): string {
	return join(cwd, ".pi", "subagent-schedules", `${sessionId}.json`);
}

export function formatJobs(jobs: StoredJob[], source: "rpc" | "file"): string {
	if (jobs.length === 0) return "无定时任务";
	const rows = jobs.map((job) => {
		const next = job.nextRun ? ` | 下次 ${job.nextRun}` : "";
		return `- ${job.id} | ${job.name} | ${job.scheduleType} ${job.schedule} | ${job.enabled ? "enabled" : "disabled"} | 已跑 ${job.runCount} 次${next}`;
	});
	const tail = source === "rpc" ? "管理:job_cancel / job_reschedule(本工具集)与 /agents 面板等效。" : "管理:取消/启停目前仅交互 /agents → Scheduled jobs(schedule-rpc patch 未打,写通道不可用)。";
	return [`共 ${jobs.length} 个定时任务(${source === "rpc" ? "RPC 实时态" : "只读镜像 schedule store"},重启不丢——session 级落盘,resume 自动重载):`, ...rows, tail].join("\n");
}

export async function listJobs(cwd: string, sessionId: string | undefined, events?: EventBusLike): Promise<JobListOutcome> {
	if (!sessionId) return { status: "no-session" };
	if (events) {
		const reply = await scheduleRpc<StoredJob[]>(events, "subagents:rpc:schedule_list", {});
		if (reply.success && Array.isArray(reply.data)) {
			const jobs = reply.data;
			return {
				status: "ok",
				text: formatJobs(jobs, "rpc"),
				source: "rpc",
				jobs: jobs.map(({ id, name, enabled, scheduleType, schedule, nextRun }) => ({ id, name, enabled, scheduleType, schedule, nextRun })),
			};
		}
	}
	let raw: string;
	try {
		raw = await readFile(storePath(cwd, sessionId), "utf8");
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return { status: "no-store" };
		return { status: "unreadable", message: String((error as Error).message ?? error) };
	}
	try {
		const parsed = JSON.parse(raw) as { jobs?: StoredJob[] };
		const jobs = Array.isArray(parsed.jobs) ? parsed.jobs : [];
		return {
			status: "ok",
			text: formatJobs(jobs, "file"),
			source: "file",
			jobs: jobs.map(({ id, name, enabled, scheduleType, schedule, nextRun }) => ({ id, name, enabled, scheduleType, schedule, nextRun })),
		};
	} catch (error) {
		return { status: "unreadable", message: String((error as Error).message ?? error) };
	}
}

export function validateSchedulePatch(patch: Record<string, unknown>): string | null {
	for (const key of Object.keys(patch)) {
		if (!["schedule", "enabled", "name", "description", "prompt"].includes(key)) return `不允许改 ${key}(白名单:schedule/enabled/name/description/prompt)`;
	}
	if (typeof patch.schedule === "string") {
		const s = patch.schedule.trim();
		if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)) {
			if (Number.isNaN(Date.parse(s))) return "once 计划不是合法 ISO 时间";
		} else if (/^[0-9*,-\/]+( [0-9*,-\/]+){5}$/.test(s)) {
			return null;
		} else {
			return "schedule 需为 6 字段 cron 或 ISO 时间";
		}
	}
	return null;
}

export function registerJobTools(pi: ExtensionAPI, Type: typeof import("typebox").Type): void {
	pi.registerTool({
		name: "job_list",
		label: "List Scheduled Jobs",
		description: "列出本会话的 pi-subagents 定时任务(id/名称/计划/enabled/已跑次数/下次触发)。patch 生效时走 RPC 实时态,否则只读镜像落盘 store。",
		promptSnippet: "定时任务清单查询",
		parameters: Type.Object({}),
		async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
			const outcome = await listJobs(ctx.cwd, ctx.sessionManager?.getSessionId?.(), pi.events);
			if (outcome.status === "ok") {
				return { content: [{ type: "text", text: outcome.text }], details: { jobs: outcome.jobs, source: outcome.source } };
			}
			if (outcome.status === "no-store") {
				return { content: [{ type: "text", text: "无定时任务" }], details: { jobs: [] } };
			}
			const message = outcome.status === "no-session" ? "sessionId 不可用(会话未初始化完),稍后重试" : `schedule store 不可读: ${outcome.message}`;
			return { content: [{ type: "text", text: message }], details: { jobs: [] }, isError: true };
		},
	});
	pi.registerTool({
		name: "job_cancel",
		label: "Cancel Scheduled Job",
		description: "取消一个 pi-subagents 定时任务(删除,含定时器)。需 schedule-rpc patch;未 patch 时报错并指引 /agents 面板。",
		promptSnippet: "定时任务取消",
		parameters: Type.Object({
			job_id: Type.String({ description: "job_list 返回的 id" }),
		}),
		async execute(_toolCallId, params) {
			const reply = await scheduleRpc(pi.events, "subagents:rpc:schedule_remove", { jobId: params.job_id });
			if (reply.success) {
				return { content: [{ type: "text", text: `已取消 ${params.job_id}(store 与定时器同删)` }], details: { cancelled: params.job_id } };
			}
			return { content: [{ type: "text", text: `取消失败: ${reply.error};未 patch 时用交互 /agents → Scheduled jobs` }], details: { cancelled: null }, isError: true };
		},
	});
	pi.registerTool({
		name: "job_reschedule",
		label: "Reschedule Job",
		description: "修改定时任务的计划/启停/名称/描述/提示词(schedule/enabled/name/description/prompt 白名单字段)。需 schedule-rpc patch。",
		promptSnippet: "定时任务改期/启停",
		parameters: Type.Object({
			job_id: Type.String({ description: "job_list 返回的 id" }),
			schedule: Type.Optional(Type.String({ description: "新计划:6 字段 cron 或 ISO 时间(once)" })),
			enabled: Type.Optional(Type.Boolean({ description: "启停" })),
			name: Type.Optional(Type.String()),
			description: Type.Optional(Type.String()),
			prompt: Type.Optional(Type.String()),
		}),
		async execute(_toolCallId, params) {
			const { job_id, ...rest } = params;
			const patch: Record<string, unknown> = {};
			for (const [key, value] of Object.entries(rest)) {
				if (value !== undefined) patch[key] = value;
			}
			const invalid = validateSchedulePatch(patch);
			if (invalid) {
				return { content: [{ type: "text", text: invalid }], details: { updated: null }, isError: true };
			}
			const reply = await scheduleRpc<StoredJob>(pi.events, "subagents:rpc:schedule_update", { jobId: job_id, patch });
			if (reply.success) {
				const job = reply.data;
				return { content: [{ type: "text", text: `已更新 ${job_id}${job ? ` → ${job.scheduleType} ${job.schedule}${job.enabled ? "" : " (disabled)"}${job.nextRun ? ` 下次 ${job.nextRun}` : ""}` : ""}` }], details: { updated: job ?? null } };
			}
			return { content: [{ type: "text", text: `更新失败: ${reply.error}` }], details: { updated: null }, isError: true };
		},
	});
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	registerJobTools(pi, Type);
}
