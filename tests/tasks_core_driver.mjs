import { TaskRegistry, readRange, parseLogTail } from "../extensions/tasks.ts";
import { writeFile } from "node:fs/promises";

const [root, scenario, payloadRaw] = process.argv.slice(2);
const payload = payloadRaw ? JSON.parse(payloadRaw) : {};
const out = {};

const registry = new TaskRegistry(root);

switch (scenario) {
	case "create": {
		const id = await registry.nextId();
		const record = await registry.recordCreate(id, payload.cmd, payload.cwd ?? root, payload.name ?? "t", payload.pid);
		out.record = { id: record.id, pid: record.pid, state: record.state };
		break;
	}
	case "mark-exit": {
		await registry.markExit(payload.id, payload.exitCode ?? 0);
		out.ok = true;
		break;
	}
	case "list": {
		out.tasks = (await registry.list()).map((task) => ({ id: task.id, state: task.state, pid: task.pid, exitCode: task.exitCode }));
		break;
	}
	case "reload": {
		const fresh = new TaskRegistry(root);
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
	case "read-range": {
		const task = await registry.find(payload.id);
		const log = await registry.readLog(payload.id);
		const result = readRange(task, log ?? Buffer.alloc(0), payload.since ?? 0);
		out.cursor = result.cursor;
		out.contentLen = Buffer.byteLength(result.content, "utf8");
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
		const range = readRange(task, buf, 0);
		out.content = range.content;
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
	default:
		throw new Error(`unknown scenario: ${scenario}`);
}

console.log(JSON.stringify(out));
