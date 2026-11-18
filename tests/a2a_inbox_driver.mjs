import factory from "../extensions/a2a-inbox.ts";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

const [scenario] = process.argv.slice(2);
delete process.env.TMUX_PANE;
const root = fs.mkdtempSync(path.join(os.tmpdir(), "a2a-driver-"));
process.env.A2A_MAILBOX_ROOT = root;
fs.mkdirSync(path.join(root, "native-inbox", "test-agent"), { recursive: true });
fs.writeFileSync(
	path.join(root, "registry.json"),
	JSON.stringify({ agents: { "test-agent": { cli: "pi", cwd: process.cwd() } } }),
);

const branch = [];
const handlers = {};
const submits = [];
const throwFirst = scenario === "throw-release";
let thrownOnce = false;
const lands = scenario === "deliver" || scenario === "throw-release" || scenario === "stale-claim";
const pi = {
	on: (event, handler) => {
		handlers[event] = handler;
	},
	sendUserMessage: (text, options) => {
		if (throwFirst && !thrownOnce) {
			thrownOnce = true;
			out.throws += 1;
			throw new Error("compaction in progress");
		}
		submits.push({ text, options });
		if (lands) {
			branch.push({ type: "message", message: { role: "user", content: [{ type: "text", text }] } });
		}
	},
};

const queueDir = path.join(root, "queue", "test-agent");
fs.mkdirSync(queueDir, { recursive: true });
const envelope = { msg_id: "m1", wake_text: "[a2a] 唤醒文本:检查注入幂等 claim 行为" };
fs.writeFileSync(path.join(queueDir, "m1.msg"), JSON.stringify(envelope));
const rcpt = path.join(root, "native-inbox", "test-agent", "rcpt-m1");
const claim = path.join(root, "native-inbox", "test-agent", "inj-m1");

const out = { submits: [], throws: 0 };
const settle = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const bump = async () => {
	fs.writeFileSync(path.join(queueDir, "trigger.msg"), "{}");
	fs.unlinkSync(path.join(queueDir, "trigger.msg"));
	await settle(300);
};

if (scenario === "foreign-claim" || scenario === "stale-claim") {
	fs.writeFileSync(claim, "99999");
	if (scenario === "stale-claim") {
		const old = new Date(Date.now() - 400000);
		fs.utimesSync(claim, old, old);
	}
}
if (scenario === "rcpt-exists") {
	fs.writeFileSync(rcpt, '{"ts":0}');
}

await factory(pi);
await handlers["session_start"]({}, { sessionManager: { getBranch: () => branch } });

if (scenario === "storm") {
	await settle(1700);
	for (let i = 0; i < 3; i += 1) {
		await bump();
		await settle(1700);
	}
} else if (scenario === "throw-release") {
	await settle(300);
	await bump();
	await settle(1700);
} else if (scenario === "rcpt-exists") {
	await settle(1700);
	await bump();
	await settle(1700);
	await bump();
} else if (scenario === "prelanded") {
	await settle(1700);
	branch.push({ type: "message", message: { role: "user", content: [{ type: "text", text: envelope.wake_text }] } });
	await bump();
} else {
	await settle(1700);
}

handlers["session_shutdown"]?.();
out.submits = submits.map((s) => ({ text: s.text, options: s.options }));
out.rcptAtEnd = fs.existsSync(rcpt);
out.claimAtEnd = fs.existsSync(claim);
console.log(JSON.stringify(out));
