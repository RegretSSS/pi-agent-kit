import { register } from "node:module";
register(new URL("./typebox_shim.mjs", import.meta.url));
import guard from "../extensions/no-long-sleep.ts";

const commands = JSON.parse(process.argv[2] ?? "[]");
let handler = null;
const pi = {
	on: (event, h) => {
		if (event === "tool_call") handler = h;
	},
};
await guard(pi);
const out = { events: [], otherToolBlocked: null, missingCommandBlocked: null, arrayCommandBlocked: null };
for (const command of commands) {
	const result = handler({ toolName: "bash", input: { command } });
	out.events.push({ command, blocked: Boolean(result?.block), reason: result?.reason ?? null });
}
out.otherToolBlocked = Boolean(handler({ toolName: "edit", input: { command: "sleep 600" } })?.block);
out.missingCommandBlocked = Boolean(handler({ toolName: "bash", input: {} })?.block);
out.arrayCommandBlocked = Boolean(handler({ toolName: "bash", input: { command: ["sleep 600"] } })?.block);
console.log(JSON.stringify(out));
