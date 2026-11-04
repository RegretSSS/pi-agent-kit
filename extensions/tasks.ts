import { appendFile, mkdir, open, readFile, readdir, rename, rm, stat, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const LOG_LIMIT_BYTES = 256 * 1024;
const LOG_KEEP_BYTES = 128 * 1024;
const POLL_INTERVAL_MS = 2000;
const STOP_GRACE_MS = 5000;
const NOTIFY_TAIL_CHARS = 200;
const TASK_TTL_MS = 7 * 24 * 3600 * 1000;

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
};

type TaskEvent =
	| { kind: "created"; record: TaskRecord }
	| { kind: "exit"; id: string; exitCode: number | null; at: string }
	| { kind: "logrotate"; id: string; logBase: number };

type ChildEntry = { child: ChildProcess; exited: boolean; exitCode: number | null };

export function readRange(record: TaskRecord, log: Buffer, since: number): { content: string; cursor: number } {
	const cursor = record.logBase + log.length;
	const start = since - record.logBase;
	if (start <= 0) return { content: log.toString("utf8"), cursor };
	if (start >= log.length) return { content: "", cursor };
	return { content: log.subarray(start).toString("utf8"), cursor };
}

export function parseLogTail(text: string, chars: number): string {
	const squashed = text.replace(/\s+/g, " ").trim();
	return squashed.length <= chars ? squashed : squashed.slice(-chars);
}

export class TaskRegistry {
	readonly root: string;
	private tasks = new Map<string, TaskRecord>();
	private loaded = false;

	constructor(root?: string) {
		this.root = root ?? join(homedir(), ".agents", "tasks");
	}

	private apply(event: TaskEvent): void {
		if (event.kind === "created") {
			this.tasks.set(event.record.id, { ...event.record });
		} else if (event.kind === "exit") {
			const task = this.tasks.get(event.id);
			if (task && task.state === "running") {
				task.state = "exited";
				task.exitCode = event.exitCode;
				task.exitAt = event.at;
			}
		} else if (event.kind === "logrotate") {
			const task = this.tasks.get(event.id);
			if (task) task.logBase = event.logBase;
		}
	}

	private async append(event: TaskEvent): Promise<void> {
		await mkdir(this.root, { recursive: true });
		await appendFile(join(this.root, "tasks.jsonl"), JSON.stringify(event) + "\n", "utf8");
		this.apply(event);
	}

	private processAlive(pid: number): boolean {
		if (pid <= 0) return false;
		try {
			process.kill(pid, 0);
			return true;
		} catch (error) {
			return (error as NodeJS.ErrnoException).code === "EPERM";
		}
	}

	async ensureLoaded(): Promise<void> {
		if (this.loaded) return;
		this.loaded = true;
		await mkdir(this.root, { recursive: true });
		const journal = join(this.root, "tasks.jsonl");
		if (!existsSync(journal)) return;
		for (const line of (await readFile(journal, "utf8")).split("\n")) {
			if (!line) continue;
			try {
				this.apply(JSON.parse(line) as TaskEvent);
			} catch {
				continue;
			}
		}
		await this.reapDeadPids();
	}

	async reapDeadPids(): Promise<TaskRecord[]> {
		const reaped: TaskRecord[] = [];
		for (const task of this.tasks.values()) {
			if (task.state !== "running") continue;
			if (this.processAlive(task.pid)) continue;
			await this.append({ kind: "exit", id: task.id, exitCode: null, at: new Date().toISOString() });
			reaped.push(this.tasks.get(task.id)!);
		}
		return reaped;
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
		const taken = new Set((await this.list()).map((task) => task.id));
		let seq = 1;
		while (taken.has(`${stamp}-${seq}`)) seq += 1;
		return `${stamp}-${seq}`;
	}

	async recordCreate(id: string, cmd: string, cwd: string, name: string, pid: number): Promise<TaskRecord> {
		const record: TaskRecord = { id, name, cmd, cwd, pid, state: "running", created: new Date().toISOString(), exitCode: null, logBase: 0 };
		await this.append({ kind: "created", record });
		return record;
	}

	async markExit(id: string, exitCode: number | null): Promise<void> {
		await this.append({ kind: "exit", id, exitCode, at: new Date().toISOString() });
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

	async shrinkOversizedLogs(): Promise<void> {
		let files: string[];
		try {
			files = await readdir(this.root);
		} catch {
			return;
		}
		for (const file of files) {
			if (!file.endsWith(".log")) continue;
			const id = file.slice(0, -4);
			const task = this.tasks.get(id);
			if (!task) continue;
			const path = this.logPath(id);
			if ((await stat(path)).size <= LOG_LIMIT_BYTES) continue;
			const buf = await readFile(path);
			const kept = buf.subarray(Math.max(0, buf.length - LOG_KEEP_BYTES));
			const handle = await open(path, "w");
			await handle.writeFile(kept);
			await handle.close();
			await this.append({ kind: "logrotate", id, logBase: task.logBase + (buf.length - kept.length) });
		}
	}

	private async compactJournal(): Promise<void> {
		const journal = join(this.root, "tasks.jsonl");
		const lines: string[] = [];
		for (const task of this.tasks.values()) {
			lines.push(JSON.stringify({ kind: "created", record: task }));
		}
		const tmp = `${journal}.${process.pid}.tmp`;
		await writeFile(tmp, lines.join("\n") + (lines.length > 0 ? "\n" : ""), "utf8");
		await rename(tmp, journal);
	}

	async gcExpired(): Promise<number> {
		const cutoff = Date.now() - TASK_TTL_MS;
		let removed = 0;
		for (const task of this.tasks.values()) {
			if (task.state !== "exited" || !task.exitAt) continue;
			if (Date.parse(task.exitAt) > cutoff) continue;
			this.tasks.delete(task.id);
			await rm(this.logPath(task.id), { force: true });
			removed += 1;
		}
		if (removed > 0) await this.compactJournal();
		return removed;
	}
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	const registry = new TaskRegistry();
	const children = new Map<string, ChildEntry>();
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	function watchChild(id: string, child: ChildProcess): ChildEntry {
		const entry: ChildEntry = { child, exited: false, exitCode: null };
		child.on("exit", (code) => {
			entry.exited = true;
			entry.exitCode = code;
		});
		child.on("error", () => {
			entry.exited = true;
			entry.exitCode = null;
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

	async function notifyFinished(tasks: TaskRecord[]): Promise<void> {
		if (tasks.length === 0) return;
		const lines: string[] = [];
		for (const task of tasks) {
			const log = await registry.readLog(task.id);
			const tail = log ? parseLogTail(log.toString("utf8"), NOTIFY_TAIL_CHARS) : "";
			lines.push(`[${task.id}] ${task.name} exit=${task.exitCode ?? "unknown"} tail: ${tail}`);
		}
		pi.sendMessage(
			{ customType: "task-notify", content: `后台任务结束 ${lines.length} 条:\n${lines.join("\n")}`, display: true },
			{ triggerTurn: true },
		);
	}

	async function sweep(): Promise<void> {
		const finished: TaskRecord[] = [];
		for (const [id, entry] of children) {
			if (!entry.exited) continue;
			children.delete(id);
			const task = registry.get(id);
			if (!task || task.state !== "running") continue;
			await registry.markExit(id, entry.exitCode);
			finished.push(registry.get(id)!);
		}
		const reaped = await registry.reapDeadPids();
		await registry.shrinkOversizedLogs();
		await notifyFinished([...finished, ...reaped]);
	}

	pi.registerTool({
		name: "task_create",
		label: "Task Create",
		description: "后台拉起长命令(setsid,与 pi 会话生命周期解耦),输出环形缓冲到 ~/.agents/tasks/<id>.log,结束时自动唤醒会话。",
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
				return { content: [{ type: "text", text: `cwd 不存在: ${cwd}` }], details: { found: false }, isError: true };
			}
			const id = await registry.nextId();
			const logHandle = await open(registry.logPath(id), "a");
			const child = spawn(params.cmd, {
				cwd,
				shell: "/bin/bash",
				detached: true,
				stdio: ["ignore", logHandle.fd, logHandle.fd],
			});
			child.unref();
			watchChild(id, child);
			await logHandle.close();
			const record = await registry.recordCreate(id, params.cmd, cwd, params.name ?? params.cmd.slice(0, 40), child.pid ?? 0);
			return {
				content: [{ type: "text", text: `task ${record.id} started (pid=${record.pid}): ${record.cmd}` }],
				details: { id: record.id, name: record.name, pid: record.pid },
			};
		},
	});

	pi.registerTool({
		name: "task_output",
		label: "Task Output",
		description: "增量读后台任务输出:传上次返回的 cursor,返回新内容与新 cursor;cursor 为 UTF-8 字节游标。",
		parameters: Type.Object({
			id: Type.String({ description: "任务 id 或 name" }),
			since: Type.Optional(Type.Integer({ description: "上次返回的 cursor,缺省从头读" })),
		}),
		async execute(_toolCallId, params) {
			const task = await registry.find(params.id);
			if (!task) {
				return { content: [{ type: "text", text: `无任务 ${params.id}` }], details: { found: false }, isError: true };
			}
			const log = await registry.readLog(task.id);
			const { content, cursor } = readRange(task, log ?? Buffer.alloc(0), params.since ?? 0);
			const protocol = `[cursor=${cursor} state=${task.state} exit=${task.exitCode ?? "-"}]`;
			return {
				content: [{ type: "text", text: `${content || "(无新输出)"}\n${protocol}` }],
				details: { cursor, state: task.state, exitCode: task.exitCode },
			};
		},
	});

	pi.registerTool({
		name: "task_stop",
		label: "Task Stop",
		description: "停止后台任务:SIGTERM→5s→SIGKILL,幂等,已停任务直接跳过。",
		parameters: Type.Object({ id: Type.String({ description: "任务 id 或 name" }) }),
		async execute(_toolCallId, params) {
			const task = await registry.find(params.id);
			if (!task) {
				return { content: [{ type: "text", text: `无任务 ${params.id}` }], details: { found: false }, isError: true };
			}
			if (task.state !== "running") {
				return { content: [{ type: "text", text: `task ${task.id} 已是 ${task.state},幂等跳过` }], details: { state: task.state } };
			}
			const entry = children.get(task.id);
			if (entry) {
				try {
					entry.child.kill("SIGTERM");
				} catch {}
				const deadline = Date.now() + STOP_GRACE_MS;
				while (!entry.exited && Date.now() < deadline) {
					await new Promise((resolve) => setTimeout(resolve, 100));
				}
				if (!entry.exited) {
					try {
						entry.child.kill("SIGKILL");
					} catch {}
				}
				children.delete(task.id);
				await registry.markExit(task.id, entry.exitCode);
			} else {
				try {
					process.kill(-task.pid, "SIGTERM");
				} catch {}
				await registry.markExit(task.id, null);
			}
			const stopped = registry.get(task.id);
			return {
				content: [{ type: "text", text: `task ${task.id} stopped (exit=${stopped?.exitCode ?? "unknown"})` }],
				details: { state: stopped?.state },
			};
		},
	});

	pi.registerTool({
		name: "task_list",
		label: "Task List",
		description: "列出后台任务(含 pi 重启后遗留的,死 pid 自动标 exited)。",
		parameters: Type.Object({}),
		async execute() {
			const tasks = await registry.list();
			if (tasks.length === 0) {
				return { content: [{ type: "text", text: "无后台任务" }], details: { tasks: [] } };
			}
			const lines = tasks.map((task) => `${task.state.padEnd(7)} ${task.id} pid=${task.pid} exit=${task.exitCode ?? "-"} ${task.name}`);
			return { content: [{ type: "text", text: lines.join("\n") }], details: { tasks: tasks.map((task) => task.id) } };
		},
	});

	pi.on("session_start", async () => {
		await registry.ensureLoaded();
		await registry.gcExpired();
		if (!pollTimer) {
			pollTimer = setInterval(() => {
				void sweep();
			}, POLL_INTERVAL_MS);
		}
	});

	pi.on("session_shutdown", async () => {
		stopPolling();
	});

	pi.on("agent_settled", async () => {
		await sweep();
	});
}
