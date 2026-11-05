import { stat } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { buildCompactInstructions } from "./compact-instructions.ts";

async function historyLikelyActive(): Promise<boolean> {
	const db = join(homedir(), ".local/share/billion-context/sessions/index.db");
	return stat(db).then(
		() => true,
		() => false,
	);
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	let pending: { brief: string; historyActive: boolean } | null = null;

	pi.registerTool({
		name: "compact",
		label: "Compact",
		description: [
			"Schedule a compaction of this conversation at the next turn boundary,",
			"keeping only what the brief specifies. Call this yourself at natural work",
			"boundaries when context is getting heavy: long task finished, milestone",
			"committed, before switching to an unrelated topic. Threshold auto-compaction",
			"remains only as a fallback; this tool lets you pick the timing and content.",
			"The generated summary starts with a <fold-index> header (topic | span | key fact | trace)",
			"so later turns can navigate back into folded history via history_search/history_read.",
		].join(" "),
		parameters: Type.Object({
			brief: Type.String({
				description: "What must survive: decisions made, file paths touched, task state, next steps",
			}),
		}),
		async execute(toolCallId, params, signal, onUpdate, ctx) {
			pending = { brief: params.brief, historyActive: await historyLikelyActive() };
			return {
				content: [{ type: "text", text: "compaction scheduled for the next turn boundary" }],
				details: {},
			};
		},
	});

	pi.on("agent_settled", async (_event, ctx) => {
		if (pending === null) return;
		const { brief, historyActive } = pending;
		pending = null;
		ctx.compact({
			customInstructions: buildCompactInstructions(brief, historyActive),
			onError: (error) => {
				if (ctx.hasUI) ctx.ui.notify(`compact failed: ${error.message}`, "error");
			},
		});
	});
}
