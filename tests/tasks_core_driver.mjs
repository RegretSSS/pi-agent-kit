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
		await registry.shrinkOversizedLogs();
		const task = registry.get(payload.id);
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
		const stale = { id: "20000101000000-9", name: "stale", cmd: "true", cwd: root, pid: 99999999, state: "exited", created: "2000-01-01T00:00:00.000Z", exitCode: 0, logBase: 0, exitAt: "2000-01-01T00:00:01.000Z" };
		await fsp.writeFile(`${root}/tasks.jsonl`, `${JSON.stringify({ kind: "created", record: stale })}\n`, "utf8");
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
	default:
		throw new Error(`unknown scenario: ${scenario}`);
}

console.log(JSON.stringify(out));
