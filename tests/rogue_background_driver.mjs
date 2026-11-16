import { register } from "node:module";
register(new URL("./typebox_shim.mjs", import.meta.url));
import guard from "../extensions/no-rogue-background.ts";

const commands = JSON.parse(process.argv[2] ?? "[]");
let handler = null;
const pi = {
	on: (event, h) => {
		if (event === "tool_call") handler = h;
	},
};
await guard(pi);
const out = { events: [], otherToolBlocked: null, missingCommandBlocked: null };
for (const command of commands) {
	const result = handler({ toolName: "bash", input: { command } });
	out.events.push({ command, blocked: Boolean(result?.block), reason: result?.reason ?? null });
}
out.otherToolBlocked = Boolean(handler({ toolName: "edit", input: { command: "nohup x &" } })?.block);
out.missingCommandBlocked = Boolean(handler({ toolName: "bash", input: {} })?.block);
console.log(JSON.stringify(out));
