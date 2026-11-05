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
};

export type JobListOutcome =
	| { status: "ok"; text: string; jobs: Array<Pick<StoredJob, "id" | "name" | "enabled" | "scheduleType" | "schedule">> }
	| { status: "no-session" }
	| { status: "no-store" }
	| { status: "unreadable"; message: string };

export function storePath(cwd: string, sessionId: string): string {
	return join(cwd, ".pi", "subagent-schedules", `${sessionId}.json`);
}

export function formatJobs(jobs: StoredJob[]): string {
	if (jobs.length === 0) return "无定时任务";
	const rows = jobs.map((job) => `- ${job.id} | ${job.name} | ${job.scheduleType} ${job.schedule} | ${job.enabled ? "enabled" : "disabled"} | 已跑 ${job.runCount} 次`);
	return [
		`共 ${jobs.length} 个定时任务(只读镜像 pi-subagents schedule store,重启不丢——session 级落盘,resume 自动重载):`,
		...rows,
		"管理:新建用 Agent 工具的 schedule 参数;取消/启停目前仅交互 /agents → Scheduled jobs(无模型侧写通道)。",
	].join("\n");
}

export async function listJobs(cwd: string, sessionId: string | undefined): Promise<JobListOutcome> {
	if (!sessionId) return { status: "no-session" };
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
			text: formatJobs(jobs),
			jobs: jobs.map(({ id, name, enabled, scheduleType, schedule }) => ({ id, name, enabled, scheduleType, schedule })),
		};
	} catch (error) {
		return { status: "unreadable", message: String((error as Error).message ?? error) };
	}
}

export function registerJobListTool(pi: ExtensionAPI, Type: typeof import("typebox").Type): void {
	pi.registerTool({
		name: "job_list",
		label: "List Scheduled Jobs",
		description: "列出本会话的 pi-subagents 定时任务(id/名称/计划/enabled/已跑次数)。只读;job 落盘随会话恢复,重启不丢。",
		promptSnippet: "定时任务清单查询",
		parameters: Type.Object({}),
		async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
			const outcome = await listJobs(ctx.cwd, ctx.sessionManager?.getSessionId?.());
			if (outcome.status === "ok") {
				return { content: [{ type: "text", text: outcome.text }], details: { jobs: outcome.jobs } };
			}
			if (outcome.status === "no-store") {
				return { content: [{ type: "text", text: "无定时任务" }], details: { jobs: [] } };
			}
			const message = outcome.status === "no-session" ? "sessionId 不可用(会话未初始化完),稍后重试" : `schedule store 不可读: ${outcome.message}`;
			return { content: [{ type: "text", text: message }], details: { jobs: [] }, isError: true };
		},
	});
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	registerJobListTool(pi, Type);
}
