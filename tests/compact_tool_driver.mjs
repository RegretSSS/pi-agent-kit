import { register } from "node:module";
register(new URL("./typebox_shim.mjs", import.meta.url));
import factory, { buildCompactInstructions } from "../extensions/compact-tool.ts";

const [scenario, payloadRaw] = process.argv.slice(2);
const payload = payloadRaw ? JSON.parse(payloadRaw) : {};
const out = {};

const handlers = {};
const sent = [];
const pi = {
	on: (event, handler) => {
		handlers[event] = handler;
	},
	registerTool: () => {},
	sendUserMessage: (text, options) => {
		sent.push({ text, options });
	},
};

if (scenario === "instructions") {
	out.text = buildCompactInstructions(payload.brief ?? "b");
} else if (scenario === "wakeup") {
	await factory(pi);
	if (!handlers["session_compact"]) throw new Error("no session_compact handler");
	await handlers["session_compact"](
		{ reason: payload.reason ?? "threshold", willRetry: payload.willRetry ?? false },
		{ sessionManager: { getSessionFile: () => payload.sessionFile ?? null } },
	);
	out.sent = sent.map((x) => x.text);out.sentOptions = sent.map((x) => x.options ?? null);
} else {
	throw new Error(`unknown scenario: ${scenario}`);
}

console.log(JSON.stringify(out));
