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
const pi = {
	on: (event, handler) => {
		handlers[event] = handler;
	},
	sendUserMessage: (text, options) => {
		submits.push({ text, options });
		if (scenario === "deliver" || (scenario === "retry" && submits.length >= 2)) {
			branch.push({ type: "message", message: { role: "user", content: [{ type: "text", text }] } });
		}
	},
};

const queueDir = path.join(root, "queue", "test-agent");
fs.mkdirSync(queueDir, { recursive: true });
const envelope = { msg_id: "m1", wake_text: "[a2a] 唤醒文本:检查 D22 同族丢信修复的落地确认行为" };
fs.writeFileSync(path.join(queueDir, "m1.msg"), JSON.stringify(envelope));
const rcpt = path.join(root, "native-inbox", "test-agent", "rcpt-m1");

const out = { submits: [], rcptAt: {} };
const settle = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

if (scenario === "prelanded") {
	await factory(pi);
	await handlers["session_start"]({}, { sessionManager: { getBranch: () => branch } });
	await settle(1700);
	branch.push({ type: "message", message: { role: "user", content: [{ type: "text", text: envelope.wake_text }] } });
	fs.writeFileSync(path.join(queueDir, "trigger.msg"), "{}");
	fs.unlinkSync(path.join(queueDir, "trigger.msg"));
	await settle(300);
} else if (scenario === "deliver" || scenario === "retry") {
	await factory(pi);
	await handlers["session_start"]({}, { sessionManager: { getBranch: () => branch } });
	await settle(1700);
	out.rcptAfterConfirm = fs.existsSync(rcpt);
	if (scenario === "retry") {
		fs.writeFileSync(path.join(queueDir, "trigger.msg"), "{}");
		fs.unlinkSync(path.join(queueDir, "trigger.msg"));
		await settle(300);
		await settle(1700);
	}
} else {
	throw new Error(`unknown scenario: ${scenario}`);
}

handlers["session_shutdown"]?.();
out.submits = submits.map((s) => ({ text: s.text, options: s.options }));
out.rcptAtEnd = fs.existsSync(rcpt);
console.log(JSON.stringify(out));
