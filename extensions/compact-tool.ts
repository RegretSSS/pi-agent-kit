import { stat } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const FOLD_INDEX_WITH_HISTORY = [
	"In addition, the summary MUST start with a fold-index header:",
	"<fold-index>",
	'- <topic> | <mNNNNN-mNNNNN span> | <key fact, keep under 40 chars> | trace: history_search("<topic>")',
	"</fold-index>",
	"One line per major phase of the folded span. The trace column is the single drill-down entry: history_search retrieves the compressed block, history_read reads it.",
	"If an earlier <fold-index> is present in the conversation, distill and merge its still-relevant lines into the new one so at most one fold-index stays alive.",
].join("\n");

const FOLD_INDEX_WITHOUT_HISTORY = [
	"In addition, the summary MUST start with a fold-index header:",
	"<fold-index>",
	"- <topic> | <mNNNNN-mNNNNN span or turn range> | <key fact, keep under 40 chars>",
	"</fold-index>",
	"One line per major phase of the folded span.",
	"If an earlier <fold-index> is present in the conversation, distill and merge its still-relevant lines into the new one so at most one fold-index stays alive.",
].join("\n");

export function buildCompactInstructions(brief: string, historyActive: boolean): string {
	const indexSpec = historyActive ? FOLD_INDEX_WITH_HISTORY : FOLD_INDEX_WITHOUT_HISTORY;
	return `${brief}\n\n${indexSpec}`;
}

const MERGED_BRIEF_CODEPOINTS = 4000;

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
			const historyActive = await historyLikelyActive();
			const merged = pending === null ? params.brief : `${pending.brief}\n---\n${params.brief}`;
			pending = { brief: Array.from(merged).slice(-MERGED_BRIEF_CODEPOINTS).join(""), historyActive };
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
				console.error(`compact failed: ${error.message}`);
				if (ctx.hasUI) ctx.ui.notify(`compact failed: ${error.message}`, "error");
			},
		});
	});
}
