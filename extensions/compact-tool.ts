import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	let pendingBrief: string | null = null;

	pi.registerTool({
		name: "compact",
		label: "Compact",
		description: [
			"Schedule a compaction of this conversation at the next turn boundary,",
			"keeping only what the brief specifies. Call this yourself at natural work",
			"boundaries when context is getting heavy: long task finished, milestone",
			"committed, before switching to an unrelated topic. Threshold auto-compaction",
			"remains only as a fallback; this tool lets you pick the timing and content.",
		].join(" "),
		parameters: Type.Object({
			brief: Type.String({
				description: "What must survive: decisions made, file paths touched, task state, next steps",
			}),
		}),
		async execute(toolCallId, params, signal, onUpdate, ctx) {
			pendingBrief = params.brief;
			return {
				content: [{ type: "text", text: "compaction scheduled for the next turn boundary" }],
				details: {},
			};
		},
	});

	pi.on("agent_settled", async (_event, ctx) => {
		if (pendingBrief === null) return;
		const brief = pendingBrief;
		pendingBrief = null;
		ctx.compact({
			customInstructions: brief,
			onError: (error) => {
				if (ctx.hasUI) ctx.ui.notify(`compact failed: ${error.message}`, "error");
			},
		});
	});
}
