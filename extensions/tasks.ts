import { appendFile, mkdir, open, readFile, readdir, rm, stat } from "node:fs/promises";
import { closeSync, existsSync, openSync, readFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const LOG_LIMIT_BYTES = 256 * 1024;
const LOG_KEEP_BYTES = 128 * 1024;
const LOG_TAIL_BYTES = 4096;
const LOG_READ_BYTES = 16 * 1024;
const TRANSCRIPT_TAIL_BYTES = 256 * 1024;
const TRANSCRIPT_READ_BYTES = 64 * 1024;
const TRANSCRIPT_TAIL_ROWS = 12;
const TRANSCRIPT_TEXT_CHARS = 300;
const TRANSCRIPT_CALL_CHARS = 160;
const DESCRIPTION_CHARS = 120;
const RESULT_TAIL_CHARS = 300;
const ERROR_HEAD_CHARS = 400;
const WAIT_MAX_SECONDS = 120;
const WAIT_INTERVAL_MS = 200;
const SLOW_INTERVAL_MS = 500;
const POLL_INTERVAL_MS = 2000;
const STOP_GRACE_MS = 5000;
const NOTIFY_TAIL_CHARS = 200;
const TASK_TTL_MS = 7 * 24 * 3600 * 1000;
const EXITED_LIST_LIMIT = 10;
const AGENT_LIST_LIMIT = 40;
const WORKFLOW_LOG_LINES = 20;
const FEATURES_TTL_MS = 10_000;
const PING_TIMEOUT_MS = 1500;
const RPC_TIMEOUT_MS = 5000;
const SUBAGENT_SESSION_NAME = /#[0-9a-f]{8}$/;
const CONTROL_CODES = /[\x00-\x08\x0b-\x1f\x7f]/g;
const CSI_SEQUENCES = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;
const AGENT_TERMINAL_STATUSES = new Set(["completed", "steered", "aborted", "stopped", "error"]);
const WORKFLOW_TERMINAL_STATUSES = new Set(["completed", "failed", "killed"]);
const HANDLE_PREFIXES: BackgroundKind[] = ["task", "agent", "wf", "job"];

export type BackgroundKind = "task" | "agent" | "wf" | "job";

export type BackgroundHandle = { kind: BackgroundKind; key: string };

export const HANDLE_HELP = "句柄形如 task:<id|名> / agent:<id|@名> / wf:<run> / job:<id>,取自 bg_list";

export function parseHandle(raw: string): BackgroundHandle | null {
	const handle = raw.trim();
	const separator = handle.indexOf(":");
	if (separator <= 0) return null;
	const kind = handle.slice(0, separator) as BackgroundKind;
	const key = handle.slice(separator + 1).trim();
	if (!key || !HANDLE_PREFIXES.includes(kind)) return null;
	return { kind, key };
}

export function sanitizeLogText(text: string): string {
	return text.replace(CSI_SEQUENCES, "").replace(CONTROL_CODES, "");
}

export type TaskState = "running" | "exited";

export type TaskRecord = {
	id: string;
	name: string;
	cmd: string;
	cwd: string;
	pid: number;
	state: TaskState;
	created: string;
	exitCode: number | null;
	logBase: number;
	exitAt?: string;
	exitSignal?: string;
	orphanAt?: string;
	procStart?: string;
	ownerPid?: number;
};

type TaskEvent =
	| { kind: "created"; record: TaskRecord }
	| { kind: "exit"; id: string; exitCode: number | null; signal?: string | null; at: string }
	| { kind: "orphan"; id: string; at: string }
	| { kind: "logrotate"; id: string; logBase: number }
	| { kind: "gc"; ids: string[] };

type ChildEntry = { child: ChildProcess; exited: boolean; exitCode: number | null; exitSignal: string | null };

export function procStartTicks(pid: number): string | undefined {
	try {
		const text = readFileSync(`/proc/${pid}/stat`, "utf8");
		const rest = text.slice(text.lastIndexOf(")") + 2);
		const field = rest.split(/\s+/)[19];
		return field || undefined;
	} catch {
		return undefined;
	}
}

export function pidIsTask(pid: number, procStart: string | undefined): boolean {
	try {
		process.kill(pid, 0);
	} catch (error) {
		return (error as NodeJS.ErrnoException).code === "EPERM";
	}
	if (!procStart) return true;
	return procStartTicks(pid) === procStart;
}

export function taskProcessAlive(task: TaskRecord): boolean {
	if (task.pid <= 0) return false;
	return pidIsTask(task.pid, task.procStart);
}

export function shellQuote(value: string): string {
	return `'${value.replace(/'/g, `'\\''`)}'`;
}

export function exitRecordingCommand(cmd: string, exitFile: string): string {
	return `trap ${shellQuote(`printf %s "$?" > ${shellQuote(exitFile)}`)} EXIT\n${cmd}`;
}

export function logWindow(record: TaskRecord, log: Buffer, since?: number): { content: string; cursor: number; skipped: number } {
	const cursor = record.logBase + log.length;
	let start = since === undefined ? Math.max(0, log.length - LOG_TAIL_BYTES) : since - record.logBase;
	start = Math.max(0, Math.min(start, log.length));
	let skipped = 0;
	if (log.length - start > LOG_READ_BYTES) {
		skipped = log.length - start - LOG_READ_BYTES;
		start += skipped;
	}
	while (start > 0 && start < log.length && (log[start] & 0xc0) === 0x80) start += 1;
	return { content: sanitizeLogText(log.subarray(start).toString("utf8")), cursor, skipped };
}

export async function waitUntil(done: () => Promise<boolean>, waitMs: number, signal?: AbortSignal, intervalMs = WAIT_INTERVAL_MS): Promise<number> {
	const start = Date.now();
	if (await done()) return 0;
	const deadline = start + waitMs;
	while (Date.now() < deadline && !signal?.aborted) {
		await new Promise((resolve) => setTimeout(resolve, Math.max(1, Math.min(intervalMs, deadline - Date.now()))));
		if (await done()) break;
	}
	return Date.now() - start;
}

export function parseLogTail(text: string, chars: number): string {
	const squashed = sanitizeLogText(text).replace(/\s+/g, " ").trim();
	return squashed.length <= chars ? squashed : squashed.slice(-chars);
}

export function headText(text: string, chars: number): string {
	const squashed = sanitizeLogText(text).replace(/\s+/g, " ").trim();
	return squashed.length <= chars ? squashed : `${squashed.slice(0, chars)}…`;
}

export function transcriptRow(message: unknown): string | null {
	if (typeof message !== "object" || message === null) return null;
	const { role, content, toolName, isError } = message as { role?: unknown; content?: unknown; toolName?: unknown; isError?: unknown };
	const parts: string[] = [];
	if (typeof content === "string") parts.push(content);
	if (Array.isArray(content)) {
		for (const block of content) {
			if (typeof block !== "object" || block === null) continue;
			const { type, text, name, arguments: args } = block as { type?: unknown; text?: unknown; name?: unknown; arguments?: unknown };
			if (type === "text" && typeof text === "string") parts.push(text);
			else if (type === "toolCall" && typeof name === "string") parts.push(`[${name}] ${JSON.stringify(args ?? {})}`);
		}
	}
	if (parts.length === 0) return null;
	const body = parts.map((part) => headText(part, TRANSCRIPT_TEXT_CHARS)).join(" ");
	if (role === "assistant") return body;
	if (role === "user") return `[user] ${body}`;
	if (role === "toolResult") return `[result ${typeof toolName === "string" ? toolName : "?"}${isError ? " ERROR" : ""}] ${body}`;
	return null;
}

export async function transcriptWindow(path: string, since?: number): Promise<{ rows: string[]; cursor: number; skipped: number } | null> {
	let size: number;
	try {
		size = (await stat(path)).size;
	} catch {
		return null;
	}
	if (size === 0) return { rows: [], cursor: 0, skipped: 0 };
	const handle = await open(path, "r");
	try {
		const tailing = since === undefined;
		let start = tailing ? Math.max(0, size - TRANSCRIPT_TAIL_BYTES) : Math.max(0, Math.min(since, size));
		let skipped = 0;
		const cap = tailing ? TRANSCRIPT_TAIL_BYTES : TRANSCRIPT_READ_BYTES;
		if (size - start > cap) {
			skipped = size - start - cap;
			start += skipped;
		}
		const buffer = Buffer.alloc(size - start);
		await handle.read(buffer, 0, buffer.length, start);
		const lines = buffer.toString("utf8").split("\n");
		const partial = lines.pop() ?? "";
		if (start > 0 && (tailing || skipped > 0)) lines.shift();
		const rows: string[] = [];
		for (const line of lines) {
			if (!line) continue;
			let entry: unknown;
			try {
				entry = JSON.parse(line);
			} catch {
				continue;
			}
			const row = transcriptRow((entry as { message?: unknown } | null)?.message);
			if (row) rows.push(row);
		}
		return { rows: tailing ? rows.slice(-TRANSCRIPT_TAIL_ROWS) : rows, cursor: size - Buffer.byteLength(partial), skipped };
	} finally {
		await handle.close();
	}
}

const TASK_ID_SHAPE = /^\d{14}-\d+(?:-[a-z0-9]{1,8})?$/;

export function claimSuffix(): string {
	return Math.random().toString(36).slice(2, 6);
}
const PID_CEILING = 4_194_304;

export function exitText(task: TaskRecord): string {
	if (task.exitCode !== null) return `code=${task.exitCode}`;
	if (task.exitSignal) return `signal:${task.exitSignal}`;
	return "unknown(reaped,无退出观测)";
}

export function isSubagentSessionName(name: string | undefined): boolean {
	return SUBAGENT_SESSION_NAME.test(name ?? "");
}

export function journalEventPlausible(event: TaskEvent): boolean {
	if (event.kind === "created") {
		const record = event.record;
		if (typeof record !== "object" || record === null) return false;
		if (!TASK_ID_SHAPE.test(String(record.id))) return false;
		if (!Number.isInteger(record.pid) || record.pid <= 1 || record.pid >= PID_CEILING) return false;
		if (typeof record.name !== "string" || record.name.length > 200) return false;
		if (typeof record.cmd !== "string" || record.cmd.length > 8192) return false;
		if (typeof record.cwd !== "string" || record.cwd.length > 4096) return false;
		if (record.state !== "running") return false;
		if (record.procStart !== undefined && typeof record.procStart !== "string") return false;
		return true;
	}
	if (event.kind === "exit" || event.kind === "logrotate" || event.kind === "orphan") {
		return TASK_ID_SHAPE.test(String(event.id));
	}
	if (event.kind === "gc") {
		return Array.isArray(event.ids) && event.ids.every((id) => TASK_ID_SHAPE.test(String(id)) && String(id).length < 4096);
	}
	return false;
}

export function canSignalTask(task: TaskRecord): boolean {
	return task.pid > 1 && task.pid < PID_CEILING && typeof task.procStart === "string" && procStartTicks(task.pid) === task.procStart;
}

export class TaskRegistry {
	readonly root: string;
	private tasks = new Map<string, TaskRecord>();
	private loaded = false;
	private journalOffset = 0;

	constructor(root?: string) {
		this.root = root ?? join(homedir(), ".agents", "tasks");
	}

	private apply(event: TaskEvent): void {
		if (event.kind === "created") {
			this.tasks.set(event.record.id, { ...event.record });
		} else if (event.kind === "orphan") {
			const task = this.tasks.get(event.id);
			if (task && task.state === "running" && !task.orphanAt) task.orphanAt = event.at;
		} else if (event.kind === "exit") {
			const task = this.tasks.get(event.id);
			if (task && task.state === "running") {
				task.state = "exited";
				task.exitCode = event.exitCode;
				task.exitSignal = event.signal ?? undefined;
				task.exitAt = event.at;
			}
		} else if (event.kind === "logrotate") {
			const task = this.tasks.get(event.id);
			if (task && event.logBase > task.logBase) task.logBase = event.logBase;
		} else if (event.kind === "gc") {
			for (const id of event.ids) this.tasks.delete(id);
		}
	}

	private async append(event: TaskEvent): Promise<void> {
		await mkdir(this.root, { recursive: true });
		await appendFile(this.journalPath(), JSON.stringify(event) + "\n", "utf8");
		this.apply(event);
	}

	private processAlive(task: TaskRecord): boolean {
		return taskProcessAlive(task);
	}

	private journalPath(): string {
		return join(this.root, "tasks.jsonl");
	}

	journalOffsetProbe(): number {
		return this.journalOffset;
	}

	async refreshFromJournal(): Promise<void> {
		if (!this.loaded) {
			await mkdir(this.root, { recursive: true });
			this.loaded = true;
		}
		let info;
		try {
			info = await stat(this.journalPath());
		} catch {
			return;
		}
		if (info.size === this.journalOffset) return;
		const buf = await readFile(this.journalPath());
		if (buf.length < this.journalOffset) {
			this.tasks.clear();
			this.journalOffset = 0;
		}
		const fresh = buf.subarray(this.journalOffset);
		const lastNewline = fresh.lastIndexOf(0x0a);
		if (lastNewline < 0) return;
		for (const line of fresh.subarray(0, lastNewline).toString("utf8").split("\n")) {
			if (!line) continue;
			try {
				const event = JSON.parse(line) as TaskEvent;
				if (!journalEventPlausible(event)) continue;
				this.apply(event);
			} catch {
				continue;
			}
		}
		this.journalOffset += lastNewline + 1;
	}

	async ensureLoaded(): Promise<void> {
		await this.refreshFromJournal();
	}

	async reapDeadPids(skipIds?: ReadonlySet<string>): Promise<TaskRecord[]> {
		const reaped: TaskRecord[] = [];
		for (const task of this.tasks.values()) {
			if (task.state !== "running") continue;
			if (skipIds?.has(task.id)) continue;
			const foreignOwner = task.ownerPid !== undefined && task.ownerPid !== process.pid;
			if (foreignOwner && this.ownerAlive(task.ownerPid!)) continue;
			if (this.processAlive(task)) continue;
			await this.markExit(task.id, null);
			reaped.push(this.tasks.get(task.id)!);
		}
		return reaped;
	}

	private ownerAlive(ownerPid: number): boolean {
		try {
			process.kill(ownerPid, 0);
			return true;
		} catch (error) {
			return (error as NodeJS.ErrnoException).code === "EPERM";
		}
	}

	async list(): Promise<TaskRecord[]> {
		await this.ensureLoaded();
		return [...this.tasks.values()].sort((a, b) => a.created.localeCompare(b.created));
	}

	async find(idOrName: string): Promise<TaskRecord | undefined> {
		const tasks = await this.list();
		return tasks.find((task) => task.id === idOrName || task.name === idOrName);
	}

	get(id: string): TaskRecord | undefined {
		return this.tasks.get(id);
	}

	async nextId(): Promise<string> {
		const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
		const taken = new Set<string>();
		for (const id of (await this.list()).map((task) => task.id)) {
			taken.add(id.startsWith(`${stamp}-`) ? id.split("-").slice(0, 2).join("-") : id);
		}
		let seq = 1;
		while (taken.has(`${stamp}-${seq}`)) seq += 1;
		for (let attempt = 0; attempt < 8; attempt += 1) {
			const candidate = `${stamp}-${seq}-${claimSuffix()}`;
			try {
				const handle = openSync(join(this.root, `${candidate}.claim`), "wx");
				closeSync(handle);
				return candidate;
			} catch {}
		}
		throw new Error("task id claim 连续失败,重试 task_create");
	}

	async recordCreate(id: string, cmd: string, cwd: string, name: string, pid: number, ownerPid: number = process.pid): Promise<TaskRecord> {
		const record: TaskRecord = { id, name, cmd, cwd, pid, state: "running", created: new Date().toISOString(), exitCode: null, logBase: 0, procStart: procStartTicks(pid), ownerPid };
		await this.append({ kind: "created", record });
		return record;
	}

	exitPath(id: string): string {
		return join(this.root, `${id}.exit`);
	}

	async readExitCode(id: string): Promise<number | null> {
		try {
			const text = (await readFile(this.exitPath(id), "utf8")).trim();
			return /^\d{1,3}$/.test(text) ? Number(text) : null;
		} catch {
			return null;
		}
	}

	async markExit(id: string, exitCode: number | null, signal: string | null = null): Promise<void> {
		const code = exitCode ?? (signal ? null : await this.readExitCode(id));
		await this.append({ kind: "exit", id, exitCode: code, signal, at: new Date().toISOString() });
	}

	async markOrphan(id: string): Promise<void> {
		const task = this.tasks.get(id);
		if (!task || task.state !== "running" || task.orphanAt) return;
		await this.append({ kind: "orphan", id, at: new Date().toISOString() });
	}

	livingForeignTasks(): TaskRecord[] {
		const out: TaskRecord[] = [];
		for (const task of this.tasks.values()) {
			if (task.state !== "running" || task.orphanAt) continue;
			if (task.ownerPid === undefined || task.ownerPid === process.pid) continue;
			if (this.ownerAlive(task.ownerPid)) continue;
			if (!this.processAlive(task)) continue;
			out.push(task);
		}
		return out;
	}

	logPath(id: string): string {
		return join(this.root, `${id}.log`);
	}

	async readLog(id: string): Promise<Buffer | null> {
		try {
			return await readFile(this.logPath(id));
		} catch {
			return null;
		}
	}

	async shrinkTask(task: TaskRecord): Promise<void> {
		if (this.shrinkInFlight.has(task.id)) return;
		const path = this.logPath(task.id);
		let size: number;
		try {
			size = (await stat(path)).size;
		} catch {
			return;
		}
		if (size <= LOG_LIMIT_BYTES) return;
		this.shrinkInFlight.add(task.id);
		try {
			const buf = await readFile(path);
			const kept = buf.subarray(Math.max(0, buf.length - LOG_KEEP_BYTES));
			const handle = await open(path, "w");
			await handle.writeFile(kept);
			await handle.close();
			await this.append({ kind: "logrotate", id: task.id, logBase: task.logBase + (buf.length - kept.length) });
		} catch {
			return;
		} finally {
			this.shrinkInFlight.delete(task.id);
		}
	}

	async shrinkOversizedLogs(): Promise<void> {
		for (const task of this.tasks.values()) {
			if (task.state === "running") await this.shrinkTask(task);
		}
	}

	private shrinkInFlight = new Set<string>();

	async sweepOrphanClaims(maxAgeMs: number = 3600_000): Promise<number> {
		let names: string[] = [];
		try {
			names = await readdir(this.root);
		} catch {
			return 0;
		}
		let removed = 0;
		for (const name of names) {
			if (!name.endsWith(".claim")) continue;
			const id = name.slice(0, -".claim".length);
			if (this.tasks.has(id)) continue;
			const path = join(this.root, name);
			try {
				const info = await stat(path);
				if (Date.now() - info.mtimeMs < maxAgeMs) continue;
				await rm(path, { force: true });
				removed += 1;
			} catch {}
		}
		return removed;
	}

	async gcExpired(): Promise<number> {
		await this.refreshFromJournal();
		const cutoff = Date.now() - TASK_TTL_MS;
		const expired: string[] = [];
		for (const task of this.tasks.values()) {
			if (task.state !== "exited" || !task.exitAt) continue;
			if (Date.parse(task.exitAt) > cutoff) continue;
			expired.push(task.id);
		}
		if (expired.length === 0) return 0;
		await this.append({ kind: "gc", ids: expired });
		for (const id of expired) {
			await rm(this.logPath(id), { force: true });
			await rm(this.exitPath(id), { force: true });
			await rm(join(this.root, `${id}.claim`), { force: true });
		}
		return expired.length;
	}
}

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
	| { status: "ok"; source: "rpc" | "file"; jobs: StoredJob[] }
	| { status: "no-session" }
	| { status: "no-store" }
	| { status: "unreadable"; message: string };

export type EventBusLike = {
	on(event: string, handler: (data: unknown) => void): () => void;
	emit(event: string, data: unknown): void;
};

export type RpcReply<T> = { success: true; data?: T } | { success: false; error: string };

export function scheduleRpc<T>(events: EventBusLike, channel: string, params: Record<string, unknown>, timeoutMs = RPC_TIMEOUT_MS, genId: () => string = defaultRequestId): Promise<RpcReply<T>> {
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
			resolve({ success: false, error: `rpc timeout: ${channel}(pi-subagents 未加载,或该通道不存在)` });
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

export function jobRow(job: StoredJob): string {
	const next = job.nextRun ? ` | 下次 ${job.nextRun}` : "";
	return `job:${job.id} | ${job.name} | ${job.scheduleType} ${job.schedule} | ${job.enabled ? "enabled" : "disabled"} | 已跑 ${job.runCount} 次${next}`;
}

export async function listJobs(cwd: string, sessionId: string | undefined, events?: EventBusLike): Promise<JobListOutcome> {
	if (!sessionId) return { status: "no-session" };
	if (events) {
		const reply = await scheduleRpc<StoredJob[]>(events, "subagents:rpc:schedule_list", {});
		if (reply.success && Array.isArray(reply.data)) {
			return { status: "ok", source: "rpc", jobs: reply.data };
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
		return { status: "ok", source: "file", jobs: Array.isArray(parsed.jobs) ? parsed.jobs : [] };
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

export type WorkflowRunSummary = {
	id: string;
	name: string;
	status: string;
	doneCount: number;
	agentCount: number;
	replayedCount: number;
	tokens: number;
	toolCalls: number;
	logCount: number;
	startedAt: number;
	completedAt?: number;
	pausedMs?: number;
	scriptPath?: string;
	journalPath?: string;
	error?: string;
};

export type WorkflowAgentRow = { label: string; state: string; error?: string; tokens?: number };

export type WorkflowStatusDetail = WorkflowRunSummary & { logs: string[]; agents: WorkflowAgentRow[] };

export const RUN_ID_SHAPE = /^wf_[a-z0-9-]+$/;

export function pathDashEncode(cwd: string): string {
	return cwd.replace(/[/\\]/g, "-").replace(/^[A-Za-z]:-/, "").replace(/^-+/, "");
}

export function workflowJournalDir(cwd: string, sessionId: string | undefined, override?: string): string | null {
	if (override) return override;
	if (!sessionId) return null;
	const uid = typeof process.getuid === "function" ? process.getuid() : 0;
	return join(tmpdir(), `pi-subagents-${uid}`, pathDashEncode(cwd), sessionId, "tasks");
}

export type JournalTailRow = { index: number; ok: boolean; text: string };

export async function workflowJournalTail(dir: string, runId: string, lines: number): Promise<{ total: number; okCount: number; tail: JournalTailRow[] } | null> {
	if (!RUN_ID_SHAPE.test(runId)) return null;
	let raw: string;
	try {
		raw = await readFile(join(dir, `${runId}.workflow.jsonl`), "utf8");
	} catch {
		return null;
	}
	const rows: JournalTailRow[] = [];
	for (const line of raw.split("\n")) {
		if (!line) continue;
		try {
			const entry = JSON.parse(line) as { index?: unknown; ok?: unknown; text?: unknown };
			if (typeof entry.index !== "number" || typeof entry.ok !== "boolean") continue;
			rows.push({ index: entry.index, ok: entry.ok, text: typeof entry.text === "string" ? entry.text : "" });
		} catch {
			continue;
		}
	}
	if (rows.length === 0) return null;
	rows.sort((a, b) => a.index - b.index);
	return { total: rows.length, okCount: rows.filter((r) => r.ok).length, tail: rows.slice(-Math.max(1, Math.min(200, Math.floor(lines)))) };
}

export function formatJournalRows(journal: { total: number; okCount: number; tail: JournalTailRow[] }): string[] {
	const rows = journal.tail.map((r) => `#${r.index} ${r.ok ? "ok" : "FAILED"} ${headText(r.text ?? "", 160)}`);
	return [`journal 回放 ${journal.total} 条,其中 ok ${journal.okCount}:`, ...rows.map((r) => `- ${r}`)];
}

type JournalTail = NonNullable<Awaited<ReturnType<typeof workflowJournalTail>>>;

export function journalLogWindow(journal: JournalTail, since?: number): { lines: string[]; cursor: number } {
	const first = journal.tail[0].index;
	const wanted = since === undefined ? journal.tail.at(-1)!.index - WORKFLOW_LOG_LINES + 1 : since;
	const rows = journal.tail.filter((row) => row.index >= Math.max(first, wanted));
	return { lines: rows.map((row) => `${row.index} ${row.ok ? "ok" : "FAILED"} ${row.text}`), cursor: journal.tail.at(-1)!.index + 1 };
}

export function workflowLogWindow(logs: string[], total: number, since?: number): { lines: string[]; cursor: number } {
	const first = total - logs.length;
	const wanted = since === undefined ? total - WORKFLOW_LOG_LINES : since;
	return { lines: logs.slice(Math.max(0, wanted - first)).map((line, index) => `${Math.max(first, wanted) + index} ${line}`), cursor: total };
}

export type AgentSnapshot = {
	id: string;
	type: string;
	description: string;
	status: string;
	depth?: number;
	handle?: string;
	alias?: string;
	parentAgentId?: string;
	workflowId?: string;
	startedAt: number;
	completedAt?: number;
	durationMs: number;
	toolUses?: number;
	sessionFile?: string;
	outputFile?: string;
	tokens?: { input: number; output: number; total: number };
	result?: string;
	error?: string;
};

export function taskRow(task: TaskRecord): string {
	const owner = task.ownerPid === undefined ? "owner=?" : task.ownerPid === process.pid ? "own" : `owner=${task.ownerPid}`;
	const flag = task.orphanAt ? " [orphan]" : "";
	const exit = task.state === "exited" ? ` | exit=${exitText(task)}` : "";
	return `task:${task.id} | ${task.state} | pid=${task.pid} | ${owner}${flag}${exit} | ${task.name}`;
}

export function agentRow(agent: AgentSnapshot): string {
	const names = [...new Set([agent.handle, agent.alias].filter((name): name is string => typeof name === "string"))].map((name) => `@${name}`).join(" ");
	const owner = agent.workflowId ? ` | wf:${agent.workflowId}` : agent.parentAgentId ? ` | 父 agent:${agent.parentAgentId}` : "";
	const seconds = Math.round(agent.durationMs / 1000);
	return `agent:${agent.id}${names ? ` ${names}` : ""} | ${agent.status} | ${agent.type}${owner} | tokens ${agent.tokens?.total ?? 0} | tools ${agent.toolUses ?? 0} | ${seconds}s | ${headText(agent.description, DESCRIPTION_CHARS)}`;
}

export function workflowRow(run: WorkflowRunSummary): string {
	const ended = run.completedAt !== undefined ? `→${new Date(run.completedAt).toISOString()}` : "";
	const err = run.error !== undefined ? ` | ${run.error}` : "";
	const replayed = run.replayedCount > 0 ? ` | replayed ${run.replayedCount}` : "";
	return `wf:${run.id} | ${run.name} | ${run.status} | agents ${run.doneCount}/${run.agentCount} | tokens ${run.tokens}${replayed} | ${new Date(run.startedAt).toISOString()}${ended}${err}`;
}

export function workflowStatusLines(detail: WorkflowStatusDetail): string[] {
	const paths = [detail.scriptPath ? `script: ${detail.scriptPath}` : null, detail.journalPath ? `journal: ${detail.journalPath}` : null].filter((line): line is string => line !== null);
	const agents = detail.agents.length > 0 ? ["agents:", ...detail.agents.map((a) => `- ${a.label} [${a.state}]${a.tokens !== undefined ? ` tokens ${a.tokens}` : ""}${a.error !== undefined ? ` | ${a.error}` : ""}`)] : [];
	const logs = detail.logs.length > 0 ? ["logs(tail):", ...detail.logs.map((l) => `- ${l}`)] : [];
	return [workflowRow(detail), ...paths, ...agents, ...logs];
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	const registry = new TaskRegistry();
	const children = new Map<string, ChildEntry>();
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let sessionIdle: (() => boolean) | null = null;
	let agentRunning = false;
	let subagentSession = false;
	let settling: Promise<TaskRecord[]> | null = null;
	let featureProbe: { at: number; features: Set<string> | null } | null = null;
	const pendingNotify: string[] = [];

function watchChild(id: string, child: ChildProcess): ChildEntry {
	const entry: ChildEntry = { child, exited: false, exitCode: null, exitSignal: null };
	if (child.exitCode !== null || child.signalCode !== null) {
		entry.exited = true;
		entry.exitCode = child.exitCode;
		entry.exitSignal = child.signalCode;
	}
	child.on("exit", (code, signal) => {
		entry.exited = true;
		entry.exitCode = code;
		entry.exitSignal = signal;
		child.unref();
	});
	child.on("error", () => {
		entry.exited = true;
		entry.exitCode = null;
		entry.exitSignal = null;
		child.unref();
	});
	children.set(id, entry);
	return entry;
}

function stopPolling(): void {
	if (pollTimer) {
		clearInterval(pollTimer);
		pollTimer = null;
	}
}

function inMaintenance(): boolean {
	return sessionIdle !== null && !sessionIdle() && !agentRunning;
}

function deliverNotify(content: string): void {
	if (inMaintenance()) {
		pendingNotify.push(content);
		return;
	}
	pi.sendMessage({ customType: "task-notify", content, display: true }, { triggerTurn: true });
}

async function notifyFinished(tasks: TaskRecord[]): Promise<void> {
	if (tasks.length === 0) return;
	const lines: string[] = [];
	for (const task of tasks) {
		const log = await registry.readLog(task.id);
		const tail = log ? parseLogTail(log.subarray(Math.max(0, log.length - 8192)).toString("utf8"), NOTIFY_TAIL_CHARS) : "";
		lines.push(`[task:${task.id}] ${task.name} exit=${exitText(task)} tail: ${tail}`);
	}
	deliverNotify(`后台任务结束 ${lines.length} 条:\n${lines.join("\n")}`);
}

function settleOwnExits(): Promise<TaskRecord[]> {
	if (!settling) {
		settling = collectOwnExits().finally(() => {
			settling = null;
		});
	}
	return settling;
}

async function collectOwnExits(): Promise<TaskRecord[]> {
	await registry.refreshFromJournal();
	const finished: TaskRecord[] = [];
	for (const [id, entry] of children) {
		if (!entry.exited) continue;
		children.delete(id);
		const task = registry.get(id);
		if (!task) continue;
		if (task.state === "running") await registry.markExit(id, entry.exitCode, entry.exitSignal);
		finished.push(registry.get(id)!);
	}
	return finished;
}

	async function sweep(): Promise<void> {
	if (pendingNotify.length > 0 && !inMaintenance()) {
		const merged = pendingNotify.join("\n\n");
		pendingNotify.length = 0;
		pi.sendMessage({ customType: "task-notify", content: merged, display: true }, { triggerTurn: true });
	}
	const finished = await settleOwnExits();
	if (subagentSession) {
		await reportOwnExits(finished);
		return;
	}
	await reapUnownedAndReport(finished);
}

async function reportOwnExits(finished: TaskRecord[]): Promise<void> {
	for (const task of finished) {
		await registry.shrinkTask(task);
	}
	await notifyFinished(finished);
}

async function reapUnownedAndReport(finished: TaskRecord[]): Promise<void> {
	const reaped = await registry.reapDeadPids(new Set(children.keys()));
	const orphaned = await registry.livingForeignTasks();
	for (const task of orphaned) {
		await registry.markOrphan(task.id);
	}
	await registry.shrinkOversizedLogs();
	await reportOwnExits([...finished, ...reaped]);
	if (orphaned.length > 0) {
		const orphanLines = orphaned.map((task) => `[task:${task.id}] ${task.name} pid=${task.pid} owner=${task.ownerPid}已死,任务仍存活`);
		deliverNotify(`孤儿任务告警 ${orphanLines.length} 条(父进程已退出,任务仍在跑,请接管或 bg_stop):\n${orphanLines.join("\n")}`);
	}
}

async function subagentFeatures(): Promise<Set<string> | null> {
	if (featureProbe && Date.now() - featureProbe.at < FEATURES_TTL_MS) return featureProbe.features;
	const reply = await scheduleRpc<{ features?: string[] }>(pi.events, "subagents:rpc:ping", {}, PING_TIMEOUT_MS);
	const features = reply.success ? new Set(Array.isArray(reply.data?.features) ? reply.data.features : []) : null;
	featureProbe = { at: Date.now(), features };
	return features;
}

async function rpcData<T>(method: string, params: Record<string, unknown>): Promise<{ data?: T; error?: string }> {
	const reply = await scheduleRpc<T>(pi.events, `subagents:rpc:${method}`, params);
	return reply.success ? { data: reply.data } : { error: reply.error };
}

type SessionContext = { cwd: string; sessionManager?: { getSessionId?: () => string | undefined } };

type AgentAccess = { state: "absent" } | { state: "unavailable" } | { state: "ok"; agents: AgentSnapshot[] };

async function listAgentSnapshots(): Promise<AgentAccess> {
	const features = await subagentFeatures();
	if (!features) return { state: "absent" };
	if (!features.has("list")) return { state: "unavailable" };
	const reply = await rpcData<{ agents?: AgentSnapshot[] }>("list", {});
	if (!Array.isArray(reply.data?.agents)) return { state: "unavailable" };
	return { state: "ok", agents: [...reply.data.agents].sort((a, b) => b.startedAt - a.startedAt) };
}

async function agentSnapshot(key: string): Promise<{ access: AgentAccess; agent?: AgentSnapshot }> {
	const access = await listAgentSnapshots();
	if (access.state === "ok") {
		if (!key.startsWith("@")) return { access, agent: access.agents.find((agent) => agent.id === key) };
		const wanted = key.slice(1).toLowerCase();
		let fallback: AgentSnapshot | undefined;
		for (const agent of access.agents) {
			if (agent.handle?.toLowerCase() !== wanted && agent.alias?.toLowerCase() !== wanted) continue;
			if (!AGENT_TERMINAL_STATUSES.has(agent.status)) return { access, agent };
			if (!fallback || agent.startedAt > fallback.startedAt) fallback = agent;
		}
		return { access, agent: fallback };
	}
	if (key.startsWith("@") || access.state === "absent") return { access };
	const features = await subagentFeatures();
	if (!features?.has("get")) return { access };
	const reply = await rpcData<{ agent?: AgentSnapshot }>("get", { agentId: key });
	return { access: { state: "ok", agents: [] }, agent: reply.data?.agent };
}

type WorkflowListing = { status: "absent" } | { status: "rpc"; runs: WorkflowRunSummary[] } | { status: "journal"; ids: string[]; dir: string; cause: string } | { status: "unreachable"; cause: string };

async function listWorkflowRuns(ctx: SessionContext): Promise<WorkflowListing> {
	const features = await subagentFeatures();
	if (!features) return { status: "absent" };
	if (features.has("kit-workflow")) {
		const reply = await rpcData<{ runs?: WorkflowRunSummary[] }>("workflow_list", {});
		if (Array.isArray(reply.data?.runs)) return { status: "rpc", runs: reply.data.runs };
	}
	const cause = "workflow 管理通道不可达(kit 分支未同步,或会话尚未绑定)";
	const dir = workflowJournalDir(ctx.cwd, ctx.sessionManager?.getSessionId?.());
	if (dir) {
		const names = await readdir(dir).catch(() => [] as string[]);
		const ids = names.filter((n) => n.endsWith(".workflow.jsonl")).map((n) => n.slice(0, -".workflow.jsonl".length)).filter((id) => RUN_ID_SHAPE.test(id));
		if (ids.length > 0) return { status: "journal", ids, dir, cause };
	}
	return { status: "unreachable", cause };
}

async function journalSectionRows(dir: string, ids: string[]): Promise<string[]> {
	const rows: string[] = [];
	for (const id of ids) {
		const tail = await workflowJournalTail(dir, id, 1);
		rows.push(`- wf:${id} | journal ${tail ? `${tail.total} 条(ok ${tail.okCount})` : "空"} | 最后 ${tail && tail.tail[0] ? (tail.tail[0].ok ? "ok" : "FAILED") : "unknown"}`);
	}
	return rows;
}

type Section = { text: string; detail: Record<string, unknown>; absent?: boolean; failed?: boolean };

const SECTION_EMPTY: Record<BackgroundKind, string> = { task: "无后台命令任务", agent: "无子代理", wf: "本会话还没有 workflow run", job: "无定时任务" };
const SECTION_LABEL: Record<BackgroundKind, string> = { task: "后台命令任务", agent: "子代理", wf: "workflow run", job: "定时任务" };
const SECTION_UNAVAILABLE = "pi-subagents 缺子代理快照通道(list/get RPC——kit 分支未同步);临时用 /agents 面板";
const WORKFLOW_UNAVAILABLE = "pi-subagents 缺 workflow 管理通道(kit 分支未同步)";
const NO_SUBAGENTS = "本会话没有 pi-subagents(未安装,或这是子代理会话)";

function textResult(text: string, details: Record<string, unknown> = {}, isError = false) {
	return { content: [{ type: "text" as const, text }], details, ...(isError ? { isError: true } : {}) };
}

function missingResult(kind: BackgroundKind, key: string) {
	const label = SECTION_LABEL[kind];
	return textResult(`无${/^[A-Za-z]/.test(label) ? " " : ""}${label} ${key}`, { found: false }, true);
}

async function taskObservation(task: TaskRecord): Promise<TaskRecord> {
	await registry.refreshFromJournal();
	const live = registry.get(task.id) ?? task;
	if (live.state === "exited" || taskProcessAlive(live)) return live;
	return { ...live, state: "exited", exitCode: await registry.readExitCode(live.id) };
}

async function stopTask(task: TaskRecord): Promise<TaskRecord | undefined> {
	if (task.state !== "running") return task;
	const entry = children.get(task.id);
	if (entry) {
		const pgid = entry.child.pid ?? 0;
		const groupSignal = (signal: "SIGTERM" | "SIGKILL") => {
			if (pgid > 1) {
				try {
					process.kill(-pgid, signal);
					return;
				} catch {}
			}
			try {
				entry.child.kill(signal);
			} catch {}
		};
		groupSignal("SIGTERM");
		const deadline = Date.now() + STOP_GRACE_MS;
		while (!entry.exited && Date.now() < deadline) {
			await new Promise((resolve) => setTimeout(resolve, 100));
		}
		if (!entry.exited) {
			groupSignal("SIGKILL");
			const killDeadline = Date.now() + 2000;
			while (!entry.exited && Date.now() < killDeadline) {
				await new Promise((resolve) => setTimeout(resolve, 100));
			}
		}
		children.delete(task.id);
		await registry.markExit(task.id, entry.exitCode, entry.exited ? entry.exitSignal : "SIGKILL");
	} else if (!canSignalTask(task)) {
		await registry.markExit(task.id, null, "already-gone");
	} else {
		try {
			process.kill(-task.pid, "SIGTERM");
		} catch {}
		const graceDeadline = Date.now() + STOP_GRACE_MS;
		while (canSignalTask(task) && Date.now() < graceDeadline) {
			await new Promise((resolve) => setTimeout(resolve, 100));
		}
		if (canSignalTask(task)) {
			try {
				process.kill(-task.pid, "SIGKILL");
			} catch {}
			await registry.markExit(task.id, null, "SIGKILL");
		} else {
			await registry.markExit(task.id, null, "SIGTERM");
		}
	}
	return registry.get(task.id);
}

async function busyBackground(ctx: SessionContext): Promise<{ handles: string[]; notes: string[] }> {
	await settleOwnExits();
	const handles: string[] = [];
	const notes: string[] = [];
	for (const task of await registry.list()) {
		if (task.state !== "running" || task.orphanAt) continue;
		if (task.ownerPid !== undefined && task.ownerPid !== process.pid) continue;
		if ((await taskObservation(task)).state !== "running") continue;
		handles.push(`task:${task.id}`);
	}
	const agents = await listAgentSnapshots();
	if (agents.state === "ok") {
		for (const agent of agents.agents) {
			if (!AGENT_TERMINAL_STATUSES.has(agent.status)) handles.push(`agent:${agent.id}`);
		}
	}
	const listing = await listWorkflowRuns(ctx);
	if (listing.status === "rpc") {
		for (const run of listing.runs) {
			if (!WORKFLOW_TERMINAL_STATUSES.has(run.status)) handles.push(`wf:${run.id}`);
		}
	} else if (listing.status !== "absent") {
		notes.push("workflow 运行态不可得(RPC 不可达),未计入");
	}
	return { handles, notes };
}

async function taskSection(): Promise<Section> {
	await settleOwnExits();
	const observed: TaskRecord[] = [];
	for (const task of await registry.list()) observed.push(await taskObservation(task));
	const running = observed.filter((task) => task.state === "running");
	const exited = observed
		.filter((task) => task.state === "exited")
		.sort((a, b) => (b.exitAt ?? b.created).localeCompare(a.exitAt ?? a.created))
		.slice(0, EXITED_LIST_LIMIT);
	if (running.length + exited.length === 0) return { text: "", detail: { tasks: [] } };
	const hidden = observed.length - running.length - exited.length;
	const summary = `[task] 命令任务 ${running.length} 个在跑${exited.length > 0 ? `,最近 ${exited.length} 条已退出` : ""}${hidden > 0 ? `(另有 ${hidden} 条更早的未列)` : ""}:`;
	return { text: [summary, ...running.map(taskRow), ...exited.map(taskRow)].join("\n"), detail: { tasks: [...running, ...exited].map((task) => task.id) } };
}

async function agentSection(): Promise<Section> {
	const access = await listAgentSnapshots();
	if (access.state === "absent") return { text: "", detail: { available: false }, absent: true };
	if (access.state === "unavailable") return { text: `[agent] ${SECTION_UNAVAILABLE}`, detail: { available: false } };
	if (access.agents.length === 0) return { text: "", detail: { agents: [] } };
	const shown = access.agents.slice(0, AGENT_LIST_LIMIT);
	const hidden = access.agents.length - shown.length;
	return { text: [`[agent] 子代理 ${access.agents.length} 个${hidden > 0 ? `(只列最近 ${AGENT_LIST_LIMIT} 个)` : ""}:`, ...shown.map(agentRow)].join("\n"), detail: { agents: shown.map((agent) => agent.id) } };
}

async function wfSection(ctx: SessionContext): Promise<Section> {
	const listing = await listWorkflowRuns(ctx);
	if (listing.status === "absent") return { text: "", detail: { runs: [] }, absent: true };
	if (listing.status === "rpc") {
		if (listing.runs.length === 0) return { text: "", detail: { runs: [] } };
		return { text: [`[wf] workflow run ${listing.runs.length} 个:`, ...listing.runs.map(workflowRow)].join("\n"), detail: { runs: listing.runs.map((run) => run.id), source: "rpc" } };
	}
	if (listing.status === "journal") {
		const rows = await journalSectionRows(listing.dir, listing.ids);
		return { text: [`[wf] RPC 不可达(${listing.cause}),本会话 journal 里的 run:`, ...rows].join("\n"), detail: { runs: listing.ids, source: "journal" } };
	}
	return { text: `[wf] workflow 清单不可达:${listing.cause}`, detail: { runs: [] }, failed: true };
}

async function jobSection(ctx: SessionContext): Promise<Section> {
	const features = await subagentFeatures();
	const outcome = await listJobs(ctx.cwd, ctx.sessionManager?.getSessionId?.(), features?.has("kit-schedule") ? pi.events : undefined);
	if (outcome.status === "ok") {
		if (outcome.jobs.length === 0) return { text: "", detail: { jobs: [], source: outcome.source } };
		const note = outcome.source === "rpc" ? "" : "(只读镜像:写通道不可用,改期/取消请用 /agents 面板)";
		return { text: [`[job] 定时任务 ${outcome.jobs.length} 个${note}:`, ...outcome.jobs.map(jobRow)].join("\n"), detail: { jobs: outcome.jobs, source: outcome.source } };
	}
	if (outcome.status === "no-store") return { text: "", detail: { jobs: [] } };
	const message = outcome.status === "no-session" ? "sessionId 不可用(会话未初始化完),稍后重试" : `schedule store 不可读: ${outcome.message}`;
	return { text: `[job] ${message}`, detail: { jobs: [] }, failed: true };
}

async function sectionFor(kind: BackgroundKind, ctx: SessionContext): Promise<Section> {
	if (kind === "task") return taskSection();
	if (kind === "agent") return agentSection();
	return kind === "wf" ? wfSection(ctx) : jobSection(ctx);
}

async function journalFallbackStatus(key: string, ctx: SessionContext, lines: number | undefined, label: string) {
	const dir = workflowJournalDir(ctx.cwd, ctx.sessionManager?.getSessionId?.());
	const journal = dir ? await workflowJournalTail(dir, key, lines ?? WORKFLOW_LOG_LINES) : null;
	if (journal) return textResult([`[journal 降级] ${label}${key} | RPC 不可达`, ...formatJournalRows(journal)].join("\n"), { journal, source: "journal" });
	return textResult(`${(await subagentFeatures()) ? WORKFLOW_UNAVAILABLE : NO_SUBAGENTS},且本会话 journal 里也没有 ${key}`, { found: false }, true);
}

	pi.registerTool({
		name: "task_create",
		label: "Task Create",
		description: "后台拉起长命令(setsid,与 pi 会话生命周期解耦),输出环形缓冲到 ~/.agents/tasks/<id>.log,结束时自动通知会话。之后用 bg_list / bg_status 跟踪、bg_log 读输出、bg_stop 停止。",
		promptSnippet: "长命令后台化(构建/训练/等待),结束自动通知",
		promptGuidelines: ["Use task_create for long-running commands instead of blocking bash; the session is woken with exit status and output tail when they finish."],
		parameters: Type.Object({
			cmd: Type.String({ description: "完整 shell 命令(bash -c 执行)" }),
			cwd: Type.Optional(Type.String({ description: "工作目录,默认当前" })),
			name: Type.Optional(Type.String({ description: "人类可读名" })),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			await registry.ensureLoaded();
			const cwd = params.cwd ?? ctx.cwd;
			if (!existsSync(cwd)) {
				return textResult(`cwd 不存在: ${cwd}`, { found: false }, true);
			}
			if (!params.cmd || params.cmd.length > 8192) {
				return textResult("cmd 需为 1..8192 字符;超长命令请落脚本文件后执行", { found: false }, true);
			}
			if (params.name !== undefined && params.name.length > 200) {
				return textResult("name 上限 200 字符", { found: false }, true);
			}
			const id = await registry.nextId();
			const logHandle = await open(registry.logPath(id), "a");
			const child = spawn("/bin/bash", ["-c", exitRecordingCommand(params.cmd, registry.exitPath(id))], {
				cwd,
				detached: true,
				stdio: ["ignore", logHandle.fd, logHandle.fd],
			});
			child.unref();
			await logHandle.close();
			const record = await registry.recordCreate(id, params.cmd, cwd, (params.name ?? params.cmd.slice(0, 40)).slice(0, 200), child.pid ?? 0);
			watchChild(id, child);
			return textResult(`task ${record.id} started (pid=${record.pid}): ${record.cmd}`, { id: record.id, name: record.name, pid: record.pid });
		},
	});

	pi.registerTool({
		name: "bg_list",
		label: "Background List",
		description: "列出后台事务:命令任务(task)、子代理(agent)、workflow run(wf)、定时任务(job),每项自带句柄,供 bg_status / bg_log / bg_stop / bg_schedule 使用。旧名对照:task_list、job_list、workflow_list → bg_list。",
		promptSnippet: "后台事务总览(命令/子代理/工作流/定时任务)",
		parameters: Type.Object({
			kind: Type.Optional(Type.String({ description: "只列一类:task | agent | wf | job;缺省四类都列" })),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			if (params.kind && !HANDLE_PREFIXES.includes(params.kind as BackgroundKind)) {
				return textResult(`kind 需为 task | agent | wf | job,收到 ${params.kind}`, { kinds: HANDLE_PREFIXES }, true);
			}
			const kinds: BackgroundKind[] = params.kind ? [params.kind as BackgroundKind] : HANDLE_PREFIXES;
			const sections: string[] = [];
			const details: Record<string, unknown> = {};
			let missing = 0;
			let last: Section | undefined;
			for (const kind of kinds) {
				last = await sectionFor(kind, ctx);
				details[kind] = last.detail;
				if (last.text) sections.push(last.text);
				else missing += 1;
			}
			if (missing === kinds.length) {
				const only = kinds.length === 1 ? SECTION_EMPTY[kinds[0]] : "无后台事务";
				return textResult(last?.absent ? `${only}(本会话没有 pi-subagents)` : only, details);
			}
			return textResult(sections.join("\n"), details, kinds.length === 1 && last?.failed === true);
		},
	});

	pi.registerTool({
		name: "bg_status",
		label: "Background Status",
		description: '查一个后台事务的状态。传 wait(秒,上限 120)则阻塞到它退出(until=exit,默认)或到本会话全部后台结束(until=idle,此时不看 handle),提前达成即返回,超时返回当前状态不报错。等后台用本工具,不要 sleep 轮询。旧名对照:task_output(等退出)→ bg_status;workflow_status → bg_status(handle="wf:…")。',
		promptSnippet: "查后台状态;wait 等到退出或全部空闲",
		parameters: Type.Object({
			handle: Type.Optional(Type.String({ description: `句柄;until=idle 时可省略。${HANDLE_HELP}` })),
			wait: Type.Optional(Type.Integer({ minimum: 1, maximum: WAIT_MAX_SECONDS, description: "最长等待秒数" })),
			until: Type.Optional(Type.String({ description: "exit(默认:句柄目标退出)| idle(本会话的命令任务/子代理/workflow 全部结束)" })),
			lines: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, description: "wf 详情的 logs/agents 尾部行数,默认 20" })),
		}),
		async execute(_toolCallId, params, signal, _onUpdate, ctx) {
			if (params.until !== undefined && params.until !== "exit" && params.until !== "idle") {
				return textResult(`until 需为 exit | idle,收到 ${params.until}`, {}, true);
			}
			if (params.until === "idle") {
				const busy = async () => (await busyBackground(ctx)).handles.length === 0;
				const waitedMs = params.wait ? await waitUntil(busy, params.wait * 1000, signal, SLOW_INTERVAL_MS) : 0;
				const state = await busyBackground(ctx);
				const waited = waitedMs > 0 ? `(waited=${Math.round(waitedMs / 1000)}s)` : "";
				const notes = state.notes.length > 0 ? `\n${state.notes.join("\n")}` : "";
				if (state.handles.length === 0) return textResult(`本会话后台已空闲${waited}${notes}`, { idle: true, waitedMs, notes: state.notes });
				return textResult(`本会话仍有 ${state.handles.length} 项后台未结束${waited}: ${state.handles.join(" ")}${notes}`, { idle: false, busy: state.handles, waitedMs, notes: state.notes });
			}
			const target = parseHandle(params.handle ?? "");
			if (!target) return textResult(`缺句柄或格式不对。${HANDLE_HELP}`, {}, true);
			if (target.kind === "job") {
				const jobs = (await jobSection(ctx)).detail.jobs as StoredJob[];
				const found = jobs.find((item) => item.id === target.key);
				return found ? textResult(jobRow(found), { job: found }) : missingResult("job", target.key);
			}
			if (target.kind === "agent") {
				const done = async () => {
					const latest = await agentSnapshot(target.key);
					return !latest.agent || AGENT_TERMINAL_STATUSES.has(latest.agent.status);
				};
				const waitedMs = params.wait ? await waitUntil(done, params.wait * 1000, signal, SLOW_INTERVAL_MS) : 0;
				const { access, agent } = await agentSnapshot(target.key);
				if (!agent) return access.state === "absent" ? textResult(NO_SUBAGENTS, { found: false }, true) : access.state === "unavailable" ? textResult(SECTION_UNAVAILABLE, { found: false }, true) : missingResult("agent", target.key);
				const lines = [agentRow(agent)];
				if (agent.error !== undefined) lines.push(`error: ${headText(agent.error, ERROR_HEAD_CHARS)}`);
				if (agent.result !== undefined) lines.push(`result(尾 ${RESULT_TAIL_CHARS} 字): ${parseLogTail(agent.result, RESULT_TAIL_CHARS)}`);
				if (waitedMs > 0) lines.push(`waited=${Math.round(waitedMs / 1000)}s`);
				return textResult(lines.join("\n"), { status: agent.status, waitedMs });
			}
			if (target.kind === "wf") {
				const features = await subagentFeatures();
				if (!features?.has("kit-workflow")) return journalFallbackStatus(target.key, ctx, params.lines, "wf:");
				const done = async () => {
					const reply = await rpcData<WorkflowStatusDetail>("workflow_status", { runId: target.key, lines: params.lines });
					return reply.data !== undefined && WORKFLOW_TERMINAL_STATUSES.has(reply.data.status);
				};
				const waitedMs = params.wait ? await waitUntil(done, params.wait * 1000, signal, SLOW_INTERVAL_MS) : 0;
				const reply = await rpcData<WorkflowStatusDetail>("workflow_status", { runId: target.key, lines: params.lines });
				if (!reply.data?.id) return reply.error?.includes("no such workflow run") ? missingResult("wf", target.key) : textResult(`bg_status失败: ${reply.error ?? "返回结构异常"}`, { found: false }, true);
				return textResult([...workflowStatusLines(reply.data), ...(waitedMs > 0 ? [`waited=${Math.round(waitedMs / 1000)}s`] : [])].join("\n"), { ...reply.data, waitedMs });
			}
			const task = await registry.find(target.key);
			if (!task) return missingResult("task", target.key);
			const done = async () => {
				await settleOwnExits();
				return (await taskObservation(task)).state === "exited";
			};
			const waitedMs = params.wait ? await waitUntil(done, params.wait * 1000, signal) : 0;
			const seen = await taskObservation(task);
			return textResult([taskRow(seen), ...(waitedMs > 0 ? [`waited=${Math.round(waitedMs / 1000)}s`] : [])].join("\n"), { state: seen.state, exitCode: seen.exitCode, exitSignal: seen.exitSignal, waitedMs });
		},
	});

	pi.registerTool({
		name: "bg_log",
		label: "Background Log",
		description: "增量读后台事务的输出:返回内容与 cursor,下次传 since=cursor 只取新增;不传 since 只取尾部。task 读命令输出(字节游标),agent 读其会话记录(工具调用与结果摘要),wf 读 log() 叙述(条数游标)。旧名对照:task_output → bg_log。",
		promptSnippet: "读后台输出(增量,带 cursor)",
		parameters: Type.Object({
			handle: Type.String({ description: `task:<id|名> / agent:<id|@名> / wf:<run>。${HANDLE_HELP}` }),
			since: Type.Optional(Type.Integer({ description: "上次返回的 cursor;缺省只取尾部" })),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const target = parseHandle(params.handle);
			if (!target) return textResult(`句柄格式不对。${HANDLE_HELP}`, {}, true);
			if (target.kind === "job") return textResult('定时任务没有输出;清单用 bg_schedule(action="list")', { found: false }, true);
			if (target.kind === "agent") {
				const { access, agent } = await agentSnapshot(target.key);
				if (!agent) return access.state === "absent" ? textResult(NO_SUBAGENTS, { found: false }, true) : access.state === "unavailable" ? textResult(SECTION_UNAVAILABLE, { found: false }, true) : missingResult("agent", target.key);
				const path = agent.outputFile ?? agent.sessionFile;
				const window = path ? await transcriptWindow(path, params.since) : null;
				if (!window) return textResult(`agent:${agent.id} 没有可读的会话记录(${path ?? "会话未落盘"})\n[state=${agent.status}]`, { state: agent.status });
				return textResult(`${window.rows.join("\n") || "(无可读记录)"}\n[cursor=${window.cursor} state=${agent.status}${window.skipped > 0 ? ` 省略=${window.skipped}字节` : ""}]`, { ...window, state: agent.status });
			}
			if (target.kind === "wf") {
				const features = await subagentFeatures();
				const reply = features?.has("kit-workflow") ? await rpcData<WorkflowStatusDetail>("workflow_status", { runId: target.key, lines: 200 }) : undefined;
				let window: { lines: string[]; cursor: number; status: string };
				if (reply?.data?.id) {
					window = { ...workflowLogWindow(reply.data.logs, reply.data.logCount, params.since), status: reply.data.status };
				} else {
					const dir = workflowJournalDir(ctx.cwd, ctx.sessionManager?.getSessionId?.());
					const journal = dir ? await workflowJournalTail(dir, target.key, 200) : null;
					if (!journal) return reply?.error?.includes("no such workflow run") ? missingResult("wf", target.key) : journalFallbackStatus(target.key, ctx, undefined, "wf:");
					window = { ...journalLogWindow(journal, params.since), status: "journal" };
				}
				const body = window.lines.length === 0 ? `wf:${target.key} 没有更新的 log() 叙述` : [`wf:${target.key} log() 叙述${window.status === "journal" ? "(journal 降级,RPC 不可达)" : ""}:`, ...window.lines].join("\n");
				return textResult(`${body}\n[cursor=${window.cursor} state=${window.status}]`, window);
			}
			const task = await registry.find(target.key);
			if (!task) return missingResult("task", target.key);
			await settleOwnExits();
			const seen = await taskObservation(task);
			const window = logWindow(seen, (await registry.readLog(seen.id)) ?? Buffer.alloc(0), params.since);
			const protocol = `[cursor=${window.cursor} state=${seen.state}${seen.state === "exited" ? ` exit=${exitText(seen)}` : ""}${window.skipped > 0 ? ` 省略=${window.skipped}字节` : ""}]`;
			return textResult(`${window.content || "(无输出)"}\n${protocol}`, { cursor: window.cursor, state: seen.state, exitCode: seen.exitCode, skipped: window.skipped });
		},
	});

	pi.registerTool({
		name: "bg_stop",
		label: "Background Stop",
		description: "停止后台事务,幂等:task 走 SIGTERM→5s→SIGKILL;agent 中止该子代理(工作流里的 agent 要停整个 wf);wf 停止 run,之后可用 SubagentWorkflow scriptPath + resumeFromRunId 续跑。旧名对照:task_stop、workflow_stop → bg_stop。",
		promptSnippet: "停止后台事务(命令/子代理/工作流)",
		parameters: Type.Object({
			handle: Type.String({ description: `task:<id|名> / agent:<id|@名> / wf:<run>。${HANDLE_HELP}` }),
		}),
		async execute(_toolCallId, params) {
			const target = parseHandle(params.handle);
			if (!target) return textResult(`句柄格式不对。${HANDLE_HELP}`, {}, true);
			if (target.kind === "job") return textResult('定时任务没有「停止」:要停用请 bg_schedule(handle="job:…", action="update", enabled=false)', { found: false }, true);
			if (target.kind === "agent") {
				let agentId = target.key;
				if (target.key.startsWith("@")) {
					const { access, agent } = await agentSnapshot(target.key);
					if (!agent) return access.state === "absent" ? textResult(NO_SUBAGENTS, { found: false }, true) : access.state === "unavailable" ? textResult(SECTION_UNAVAILABLE, { found: false }, true) : missingResult("agent", target.key);
					agentId = agent.id;
				}
				const reply = await scheduleRpc(pi.events, "subagents:rpc:stop", { agentId });
				if (reply.success) return textResult(`已停止 agent:${agentId}`, { stopped: agentId });
				if (reply.error === "Agent is not running") return textResult(`agent:${agentId} 已结束,幂等跳过`, { stopped: false });
				if (reply.error === "Agent is not found" || reply.error === "Agent not found") return missingResult("agent", target.key);
				const hint = reply.error.includes("owned by another agent or workflow") ? "\n它归属 workflow 或另一个 agent,不能单独停;工作流的 agent 请停整个 run(句柄见 bg_list 的 wf: 行)" : "";
				return textResult(`bg_stop失败: ${reply.error}${hint}`, { stopped: false }, true);
			}
			if (target.kind === "wf") {
				const features = await subagentFeatures();
				if (!features?.has("kit-workflow")) return textResult(`${features ? WORKFLOW_UNAVAILABLE : NO_SUBAGENTS},无法停止 ${target.key}`, { stopped: false }, true);
				const reply = await rpcData<{ stopped: boolean; status?: string }>("workflow_stop", { runId: target.key });
				if (reply.data) {
					const text = reply.data.stopped ? `已停止 wf:${target.key}(子 agent 一并中止;续跑用 SubagentWorkflow scriptPath + resumeFromRunId)` : `wf:${target.key} 无需停止(已 abort,状态 ${reply.data.status ?? "unknown"})`;
					return textResult(text, reply.data);
				}
				return textResult(`bg_stop失败: ${reply.error ?? "返回结构异常"}`, { stopped: false }, true);
			}
			const task = await registry.find(target.key);
			if (!task) return missingResult("task", target.key);
			if (task.state !== "running") return textResult(`${taskRow(task)}\n已退出,幂等跳过`, { state: task.state });
			const stopped = await stopTask(task);
			return textResult(`${taskRow(stopped ?? task)}\n已停止`, { state: stopped?.state, exitCode: stopped?.exitCode });
		},
	});

	pi.registerTool({
		name: "bg_schedule",
		label: "Background Schedule",
		description: '管理 pi-subagents 定时任务:列清单(list)、取消(cancel)、改计划/启停/名称/描述/提示词(update)。旧名对照:job_list → bg_schedule(action="list"),job_cancel → action="cancel",job_reschedule → action="update"。',
		promptSnippet: "定时任务清单/取消/改期",
		parameters: Type.Object({
			action: Type.String({ description: "list | cancel | update" }),
			handle: Type.Optional(Type.String({ description: "job:<id>;cancel 与 update 必填" })),
			schedule: Type.Optional(Type.String({ description: "update:新计划,6 字段 cron 或 ISO 时间(once)" })),
			enabled: Type.Optional(Type.Boolean({ description: "update:启停" })),
			name: Type.Optional(Type.String({ description: "update:名称" })),
			description: Type.Optional(Type.String({ description: "update:描述" })),
			prompt: Type.Optional(Type.String({ description: "update:提示词" })),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			if (params.action === "list") {
				const section = await jobSection(ctx);
				return textResult(section.text || SECTION_EMPTY.job, section.detail, section.failed === true);
			}
			if (params.action !== "cancel" && params.action !== "update") return textResult(`action 需为 list | cancel | update,收到 ${params.action}`, {}, true);
			const target = parseHandle(params.handle ?? "");
			if (!target || target.kind !== "job") return textResult(`${params.action} 需要 job:<id> 句柄,取自 bg_schedule(action="list")`, {}, true);
			const features = await subagentFeatures();
			if (!features?.has("kit-schedule")) return textResult(features ? "pi-subagents 缺定时任务写通道(kit 分支未同步);请用交互 /agents → Scheduled jobs" : NO_SUBAGENTS, { updated: null }, true);
			if (params.action === "cancel") {
				const reply = await scheduleRpc(pi.events, "subagents:rpc:schedule_remove", { jobId: target.key });
				return reply.success ? textResult(`已取消 job:${target.key}(store 与定时器同删)`, { cancelled: target.key }) : textResult(`取消失败: ${reply.error}`, { cancelled: null }, true);
			}
			const patch: Record<string, unknown> = {};
			for (const key of ["schedule", "enabled", "name", "description", "prompt"] as const) {
				if (params[key] !== undefined) patch[key] = params[key];
			}
			const invalid = validateSchedulePatch(patch);
			if (invalid) return textResult(invalid, { updated: null }, true);
			const reply = await scheduleRpc<StoredJob>(pi.events, "subagents:rpc:schedule_update", { jobId: target.key, patch });
			if (!reply.success) return textResult(`更新失败: ${reply.error}`, { updated: null }, true);
			const job = reply.data;
			return textResult(`已更新 job:${target.key}${job ? ` → ${job.scheduleType} ${job.schedule}${job.enabled ? "" : " (disabled)"}${job.nextRun ? ` 下次 ${job.nextRun}` : ""}` : ""}`, { updated: job ?? null });
		},
	});

	pi.on("session_start", async (_event, ctx) => {
		sessionIdle = () => ctx.isIdle();
		subagentSession = isSubagentSessionName(ctx.sessionManager?.getSessionName?.());
		await registry.ensureLoaded();
		if (!subagentSession) {
			await registry.reapDeadPids(new Set(children.keys()));
			await registry.sweepOrphanClaims();
			await registry.gcExpired();
		}
		if (!pollTimer) {
			pollTimer = setInterval(() => {
				sweep().catch(() => {});
			}, POLL_INTERVAL_MS);
		}
	});

	pi.on("session_shutdown", async () => {
		stopPolling();
	});

	pi.on("agent_start", async () => {
		agentRunning = true;
	});

	pi.on("agent_end", async () => {
		agentRunning = false;
	});

	pi.on("agent_settled", async () => {
		await sweep();
	});
}
