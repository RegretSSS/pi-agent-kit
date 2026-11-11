import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const FOLD_INDEX_SPEC = [
	"In addition, the summary MUST start with a fold-index header:",
	"<fold-index>",
	"- <topic> | <mNNNNN-mNNNNN span or turn range> | <key fact, keep under 40 chars>",
	"</fold-index>",
	"One line per major phase of the folded span.",
	"If an earlier <fold-index> is present in the conversation, distill and merge its still-relevant lines into the new one so at most one fold-index stays alive.",
].join("\n");

export function buildCompactInstructions(brief: string): string {
	return `${brief}\n\n${FOLD_INDEX_SPEC}`;
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	let pending: string | null = null;

	pi.registerTool({
		name: "compact",
		label: "Compact",
		description: [
			"Schedule a compaction of this conversation at the next turn boundary,",
			"keeping only what the brief specifies. Call this yourself at natural work",
			"boundaries when context is getting heavy: long task finished, milestone",
			"committed, before switching to an unrelated topic. Watch the [ctx ...] gauge line",
			"in tool results: at 30% it warns to time the compaction, at 50% it demands one",
			"immediately — calling this proactively keeps your own context quality; threshold",
			"auto-compaction remains only as a last-resort fallback. After the compaction",
			"completes you receive a [compact 完成] message: re-orient via the fold-index and",
			"resume the unfinished work before reporting back. The generated summary starts",
			"with a <fold-index> header (topic | span | key fact) so later turns can navigate",
			"back into folded history by scanning the index lines.",
		].join(" "),
		parameters: Type.Object({
			brief: Type.String({
				description: "What must survive: decisions made, file paths touched, task state, next steps",
			}),
		}),
		async execute(toolCallId, params, signal, onUpdate, ctx) {
			const merged = pending === null ? params.brief : `${pending}\n---\n${params.brief}`;
			pending = Array.from(merged).slice(-4000).join("");
			return {
				content: [{ type: "text", text: "compaction scheduled for the next turn boundary" }],
				details: {},
			};
		},
	});

	pi.on("agent_settled", async (_event, ctx) => {
		if (pending === null) return;
		const brief = pending;
		pending = null;
		ctx.compact({
			customInstructions: buildCompactInstructions(brief),
			onError: (error) => {
				console.error(`compact failed: ${error.message}`);
				if (ctx.hasUI) ctx.ui.notify(`compact failed: ${error.message}`, "error");
			},
		});
	});

	pi.on("session_compact", async (event, ctx) => {
		if (event.willRetry) return;
		const trigger = event.reason === "manual" ? "手动 /compact" : event.reason === "overflow" ? "溢出恢复" : "水位触发";
		const sessionFile = ctx.sessionManager.getSessionFile();
		const trace = sessionFile ? ` 原文全量在本会话文件 ${sessionFile},需要折叠前的细节时直接 read/grep 它。` : "";
		pi.sendUserMessage(`[compact 完成] 上下文已整理(${trigger})。按摘要头部的 fold-index 重新定位任务状态,继续未完成的工作;若已到自然边界,向用户收尾汇报。${trace}`);
	});
}
