import { register } from "node:module";
register(new URL("./typebox_shim.mjs", import.meta.url));
import { TaskRegistry, logWindow, parseLogTail } from "../extensions/tasks.ts";
import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join } from "node:path";

const [root, scenario, payloadRaw] = process.argv.slice(2);
const payload = payloadRaw ? JSON.parse(payloadRaw) : {};
const out = {};

const registry = new TaskRegistry(root);

const settle = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function bootFactory(options = {}) {
	const { default: factory } = await import("../extensions/tasks.ts");
	const tools = {};
	const handlers = {};
	const sent = [];
	const pi = {
		on: (event, handler) => {
			handlers[event] = handler;
		},
		registerTool: (tool) => {
			tools[tool.name] = tool;
		},
		registerCommand: () => {},
		sendMessage: (message) => {
			sent.push(message.content);
		},
		events: { on: () => () => {}, emit: () => {} },
	};
	await factory(pi);
	const idle = { value: options.startIdle ?? true };
	const ctx = {
		cwd: root,
		sessionManager: { getBranch: () => [], getSessionName: () => options.sessionName ?? "main session" },
		isIdle: () => idle.value,
	};
	await handlers["session_start"]({}, ctx);
	return { tools, handlers, sent, ctx, idle };
}

const text = (result) => result.content?.[0]?.text ?? "";

switch (scenario) {
	case "create": {
		const id = await registry.nextId();
		const record = await registry.recordCreate(id, payload.cmd, payload.cwd ?? root, payload.name ?? "t", payload.pid);
		out.record = { id: record.id, pid: record.pid, state: record.state };
		break;
	}
	case "mark-exit": {
		await registry.markExit(payload.id, payload.exitCode ?? 0, payload.signal ?? null);
		out.ok = true;
		break;
	}
	case "exit-signal": {
		const id = await registry.nextId();
		await registry.recordCreate(id, "sig", root, "sig-test", 4194303);
		await registry.markExit(id, null, "SIGTERM");
		const viewer = new TaskRegistry(root);
		const task = await viewer.find(id);
		const { exitText } = await import("../extensions/tasks.ts");
		out.reloadSignal = task.exitSignal ?? null;
		out.reloadCode = task.exitCode;
		out.text = exitText(task);
		out.plausible = (await import("../extensions/tasks.ts")).journalEventPlausible({ kind: "orphan", id });
		break;
	}
	case "orphan": {
		const { spawn: sp } = await import("node:child_process");
		const aliveOwner = sp("sleep", ["8"], { stdio: "ignore" });
		const realTask = sp("sleep", ["8"], { stdio: "ignore" });
		const foreignId = await registry.nextId();
		await registry.recordCreate(foreignId, "orphan-cand", root, "orphan-candidate", realTask.pid ?? 0, aliveOwner.pid ?? 0);
		const ownId = await registry.nextId();
		await registry.recordCreate(ownId, "own", root, "own-task", 4194303);
		await registry.list();
		out.foreignWhileOwnerAlive = registry.livingForeignTasks().map((t) => t.id);
		out.ownExcluded = registry.livingForeignTasks().length;
		aliveOwner.kill();
		await new Promise((resolve) => setTimeout(resolve, 100));
		out.foreignAfterOwnerDeath = registry.livingForeignTasks().map((t) => t.id);
		await registry.markOrphan(foreignId);
		await registry.markOrphan(foreignId);
		const viewer = new TaskRegistry(root);
		const seen = new Set((await viewer.list()).filter((t) => t.orphanAt).map((t) => t.id));
		out.orphanIds = [...seen];
		const journalText = await (await import("node:fs/promises")).readFile(`${root}/tasks.jsonl`, "utf8");
		out.journalOrphanEvents = (journalText.match(/"kind":"orphan"/g) ?? []).length;
		realTask.kill();
		break;
	}
	case "list": {
		out.tasks = (await registry.list()).map((task) => ({ id: task.id, state: task.state, pid: task.pid, exitCode: task.exitCode }));
		break;
	}
	case "reload": {
		const fresh = new TaskRegistry(root);
		await fresh.list();
		await fresh.reapDeadPids();
		out.tasks = (await fresh.list()).map((task) => ({ id: task.id, state: task.state, pid: task.pid, exitCode: task.exitCode }));
		break;
	}
	case "write-log": {
		const chunk = "x".repeat(1024);
		const text = chunk.repeat(Math.ceil(payload.kb / 1));
		await writeFile(`${root}/${payload.id}.log`, text, "utf8");
		out.bytes = Buffer.byteLength(text);
		break;
	}
	case "shrink": {
		await registry.ensureLoaded();
		const task = await registry.find(payload.id);
		if (task) await registry.shrinkTask(task);
		out.logBase = task ? task.logBase : null;
		break;
	}
	case "log-window": {
		await registry.ensureLoaded();
		const task = await registry.find(payload.id);
		const log = await registry.readLog(payload.id);
		const window = logWindow(task, log ?? Buffer.alloc(0), payload.since);
		out.cursor = window.cursor;
		out.contentLen = Buffer.byteLength(window.content, "utf8");
		out.skipped = window.skipped;
		break;
	}
	case "tail": {
		out.tail = parseLogTail(payload.text, payload.chars);
		break;
	}
	case "gc-prep": {
		const fsp = await import("node:fs/promises");
		const stale = { id: "20000101000000-9", name: "stale", cmd: "true", cwd: root, pid: 4194303, state: "running", created: "2000-01-01T00:00:00.000Z", exitCode: null, logBase: 0 };
		const events = [
			{ kind: "created", record: stale },
			{ kind: "exit", id: stale.id, exitCode: 0, at: "2000-01-01T00:00:01.000Z" },
		];
		await fsp.writeFile(`${root}/tasks.jsonl`, events.map((e) => JSON.stringify(e)).join("\n") + "\n", "utf8");
		await fsp.writeFile(`${root}/20000101000000-9.log`, "old", "utf8");
		await fsp.writeFile(`${root}/20000101000000-9.exit`, "0", "utf8");
		out.ok = true;
		break;
	}
	case "gc": {
		const fsp = await import("node:fs/promises");
		const fresh = new TaskRegistry(root);
		await fresh.list();
		out.removed = await fresh.gcExpired();
		out.remaining = (await fresh.list()).map((task) => task.id);
		out.logGone = !(await fsp.stat(`${root}/20000101000000-9.log`).then(
			() => true,
			() => false,
		));
		out.exitGone = !(await fsp.stat(`${root}/20000101000000-9.exit`).then(
			() => true,
			() => false,
		));
		out.journal = await fsp.readFile(`${root}/tasks.jsonl`, "utf8");
		break;
	}
	case "cross-session-exit": {
		const fsp = await import("node:fs/promises");
		const created = await registry.nextId();
		await registry.recordCreate(created, "sleep 60", root, "cross", 4194303);
		const foreignExit = { kind: "exit", id: created, exitCode: 7, at: "2026-01-01T00:00:00.000Z" };
		await fsp.appendFile(`${root}/tasks.jsonl`, JSON.stringify(foreignExit) + "\n", "utf8");
		const viewer = new TaskRegistry(root);
		out.state = (await viewer.find(created)).state;
		out.exitCode = (await viewer.find(created)).exitCode;
		break;
	}
	case "escape-filter": {
		const task = { id: "esc-1", name: "esc", cmd: "x", cwd: root, pid: 0, state: "exited", created: "2026-01-01T00:00:00.000Z", exitCode: 0, logBase: 0 };
		const buf = Buffer.from("clean\x1b[31mred\x1b[0m\ndone\n", "utf8");
		out.content = logWindow(task, buf, 0).content;
		break;
	}
	case "offset-probe": {
		const created = await registry.nextId();
		await registry.recordCreate(created, "x", root, "probe", 4194303);
		await registry.refreshFromJournal();
		out.offsetFirst = registry.journalOffsetProbe();
		await registry.refreshFromJournal();
		out.offsetSecondNoop = registry.journalOffsetProbe();
		const { stat: st } = await import("node:fs/promises");
		out.journalSize = (await st(`${root}/tasks.jsonl`)).size;
		break;
	}
	case "forge-journal": {
		const fsp = await import("node:fs/promises");
		const forged = [
			JSON.stringify({ kind: "created", record: { id: "not-an-id", name: "x", cmd: "x", cwd: root, pid: 100, state: "running", created: "2026-01-01T00:00:00.000Z", exitCode: null, logBase: 0 } }),
			JSON.stringify({ kind: "created", record: { name: "ghost-no-id", pid: 1, state: "running" } }),
			JSON.stringify({ kind: "created", record: { id: "20260101000000-1", name: "huge", cmd: "y".repeat(9000), cwd: root, pid: 100, state: "running", created: "2026-01-01T00:00:00.000Z", exitCode: null, logBase: 0 } }),
			JSON.stringify({ kind: "gc", ids: ["../../etc"] }),
		].join("\n");
		await fsp.appendFile(`${root}/tasks.jsonl`, forged + "\n", "utf8");
		const fresh = new TaskRegistry(root);
		out.names = (await fresh.list()).map((t) => t.name);
		break;
	}
	case "reap-owner": {
		const { spawn: sp } = await import("node:child_process");
		const aliveOwner = sp("sleep", ["8"], { stdio: "ignore" });
		const selfId = await registry.nextId();
		await registry.recordCreate(selfId, "self", root, "self-owned", 4194303);
		const deadId = await registry.nextId();
		await registry.recordCreate(deadId, "dead", root, "dead-owner", 4194303, 4194303);
		const yieldId = await registry.nextId();
		await registry.recordCreate(yieldId, "yield", root, "live-foreign-owner", 4194303, aliveOwner.pid ?? 0);
		await registry.list();
		await registry.reapDeadPids();
		let all = await registry.list();
		out.selfState = all.find((t) => t.id === selfId)?.state;
		out.deadOwnerState = all.find((t) => t.id === deadId)?.state;
		out.yieldWhileOwnerAlive = all.find((t) => t.id === yieldId)?.state;
		aliveOwner.kill();
		await new Promise((resolve) => setTimeout(resolve, 100));
		await registry.reapDeadPids();
		all = await registry.list();
		out.yieldAfterOwnerDeath = all.find((t) => t.id === yieldId)?.state;
		break;
	}
	case "exit-command": {
		const { exitRecordingCommand } = await import("../extensions/tasks.ts");
		const { execFile } = await import("node:child_process");
		const run = async (name, cmd) => {
			const file = join(root, name);
			const outcome = await new Promise((resolve) => {
				execFile("/bin/bash", ["-c", exitRecordingCommand(cmd, file)], (error, stdout) => {
					resolve({ code: error ? error.code : 0, stdout });
				});
			});
			return { ...outcome, file: existsSync(file) ? await readFile(file, "utf8") : null };
		};
		out.plain = await run("plain.exit", "echo hi; exit 7");
		out.quoted = await run(`it's "q" $d \\.exit`, "exit 3");
		out.execed = await run("exec.exit", "exec true");
		out.failed = await run("failed.exit", "false");
		out.trapKeepsStatus = await run("trap.exit", "set -e; false; echo unreachable");
		break;
	}
	case "wait-until": {
		const { waitUntil } = await import("../extensions/tasks.ts");
		const mode = payload.mode;
		let calls = 0;
		const started = Date.now();
		const controller = new AbortController();
		if (mode === "abort") setTimeout(() => controller.abort(), payload.abortAfterMs ?? 100);
		const done = async () => {
			calls += 1;
			return mode === "instant" || (mode === "flip" && Date.now() - started >= (payload.delayMs ?? 250));
		};
		const waitedMs = await waitUntil(done, payload.waitMs ?? 400, mode === "abort" ? controller.signal : undefined, payload.intervalMs ?? 50);
		out.result = { waitedMs, calls };
		break;
	}
	case "factory-e2e": {
		const { tools, handlers, sent, ctx, idle } = await bootFactory();
		const created = await tools.task_create.execute("t1", { cmd: payload.cmd ?? "exit 42" }, undefined, undefined, ctx);
		const id = created.details.id;
		await settle(payload.firstWaitMs ?? 3500);
		const listed = await tools.bg_list.execute("t2", { kind: "task" }, undefined, undefined, ctx);
		out.listText = text(listed);
		if (payload.notifyPhases) {
			sent.length = 0;
			idle.value = false;
			await handlers["agent_start"]({}, ctx);
			const duringRun = await tools.task_create.execute("t3", { cmd: "exit 3" }, undefined, undefined, ctx);
			await settle(3000);
			out.runSentCount = sent.length;
			out.runSentText = sent[0] ?? null;
			await handlers["agent_end"]({}, ctx);
			sent.length = 0;
			const duringMaintenance = await tools.task_create.execute("t4", { cmd: "exit 4" }, undefined, undefined, ctx);
			await settle(3000);
			out.maintenanceSentCount = sent.length;
			idle.value = true;
			await settle(3000);
			out.flushedSentCount = sent.length;
			out.flushedText = sent[0] ?? null;
			out.phaseIds = [duringRun.details.id, duringMaintenance.details.id];
		}
		out.notifyText = payload.notifyPhases ? null : (sent.find((t) => t.includes(id)) ?? null);
		await handlers["session_shutdown"]?.();
		break;
	}
	case "factory-two-sessions": {
		const { isSubagentSessionName } = await import("../extensions/tasks.ts");
		const { mkdirSync } = await import("node:fs");
		mkdirSync(root, { recursive: true });
		const parent = await bootFactory();
		const child = await bootFactory({ sessionName: "general-purpose#1a2b3c4d" });
		const parentOwned = await parent.tools.task_create.execute("p1", { cmd: "sleep 1; exit 7", name: "parent-owned" }, undefined, undefined, parent.ctx);
		await settle(4500);
		const viewer = new TaskRegistry();
		await viewer.ensureLoaded();
		out.parentOwnedId = parentOwned.details.id;
		out.parentSent = parent.sent.filter((text) => text.includes(parentOwned.details.id));
		out.childSent = child.sent.slice();
		out.recordedExitCode = viewer.get(parentOwned.details.id).exitCode;
		const childList = await child.tools.bg_list.execute("c0", { kind: "task" }, undefined, undefined, child.ctx);
		out.childSeesParentTask = text(childList).includes(parentOwned.details.id);
		child.sent.length = 0;
		const childOwned = await child.tools.task_create.execute("c1", { cmd: "exit 9", name: "child-owned" }, undefined, undefined, child.ctx);
		await settle(3500);
		out.childOwnSent = child.sent.filter((text) => text.includes(childOwned.details.id));
		out.classifier = ["general-purpose#1a2b3c4d", "Explore#0f9e8d7c", "main session", "report#1234567", "report#123456789", "report#zzzzzzzz", undefined].map((name) => isSubagentSessionName(name));
		await parent.handlers["session_shutdown"]?.();
		await child.handlers["session_shutdown"]?.();
		break;
	}
	case "factory-bg-flow": {
		const { tools, handlers, ctx } = await bootFactory();
		const created = await tools.task_create.execute("t1", { cmd: "sleep 1; echo FLOW_MARK; exit 6", name: "flow" }, undefined, undefined, ctx);
		const handle = `task:${created.details.id}`;
		const status = await tools.bg_status.execute("t2", { handle }, undefined, undefined, ctx);
		out.running = text(status);
		out.runningState = status.details.state;
		const log = await tools.bg_log.execute("t3", { handle }, undefined, undefined, ctx);
		out.logCursor = log.details.cursor;
		out.logState = log.details.state;
		const waited = await tools.bg_status.execute("t4", { handle, wait: 10 }, undefined, undefined, ctx);
		out.waitedText = text(waited);
		out.waitedMs = waited.details.waitedMs;
		out.waitedState = waited.details.state;
		out.waitedCode = waited.details.exitCode;
		const final = await tools.bg_log.execute("t5", { handle }, undefined, undefined, ctx);
		out.finalText = text(final);
		out.finalCursor = final.details.cursor;
		const again = await tools.bg_log.execute("t6", { handle, since: final.details.cursor }, undefined, undefined, ctx);
		out.againText = text(again);
		const stopped = await tools.bg_stop.execute("t7", { handle }, undefined, undefined, ctx);
		out.stopText = text(stopped);
		const bad = await tools.bg_status.execute("t8", { handle: "nope" }, undefined, undefined, ctx);
		out.badText = text(bad);
		out.badIsError = bad.isError === true;
		const missing = await tools.bg_log.execute("t9", { handle: "task:20990101000000-9" }, undefined, undefined, ctx);
		out.missingIsError = missing.isError === true;
		const listed = await tools.bg_list.execute("t10", {}, undefined, undefined, ctx);
		out.listText = text(listed);
		out.listIsError = listed.isError === true;
		out.names = Object.keys(tools).sort();
		await handlers["session_shutdown"]?.();
		break;
	}
	case "factory-bg-log-cap": {
		const { tools, handlers, ctx } = await bootFactory();
		const created = await tools.task_create.execute("c1", { cmd: "head -c 20000 /dev/zero | tr '\\0' a; echo; echo TAIL_MARK", name: "big" }, undefined, undefined, ctx);
		const handle = `task:${created.details.id}`;
		const waited = await tools.bg_status.execute("c2", { handle, wait: 10 }, undefined, undefined, ctx);
		out.state = waited.details.state;
		const split = (result) => {
			const body = text(result);
			const cut = body.lastIndexOf("\n");
			return { content: body.slice(0, cut), protocol: body.slice(cut + 1), details: result.details };
		};
		const tail = split(await tools.bg_log.execute("c3", { handle }, undefined, undefined, ctx));
		out.tail = { len: Buffer.byteLength(tail.content, "utf8"), ends: tail.content.endsWith("TAIL_MARK\n"), protocol: tail.protocol };
		const full = split(await tools.bg_log.execute("c4", { handle, since: 0 }, undefined, undefined, ctx));
		out.full = { len: Buffer.byteLength(full.content, "utf8"), protocol: full.protocol };
		out.again = text(await tools.bg_log.execute("c5", { handle, since: tail.details.cursor }, undefined, undefined, ctx));
		await handlers["session_shutdown"]?.();
		break;
	}
	case "factory-reload-exit-code": {
		const first = await bootFactory();
		const created = await first.tools.task_create.execute("r1", { cmd: "sleep 1; exit 7", name: "reload-probe" }, undefined, undefined, first.ctx);
		await first.handlers["session_shutdown"]?.();
		const second = await bootFactory();
		const waited = await second.tools.bg_status.execute("r2", { handle: `task:${created.details.id}`, wait: 10 }, undefined, undefined, second.ctx);
		out.state = waited.details.state;
		out.code = waited.details.exitCode;
		out.text = text(waited);
		await settle(2500);
		const viewer = new TaskRegistry();
		await viewer.ensureLoaded();
		out.journalCode = viewer.get(created.details.id).exitCode;
		out.listed = text(await second.tools.bg_list.execute("r3", { kind: "task" }, undefined, undefined, second.ctx));
		await second.handlers["session_shutdown"]?.();
		break;
	}
	default:
		throw new Error(`unknown scenario: ${scenario}`);
}

console.log(JSON.stringify(out));
