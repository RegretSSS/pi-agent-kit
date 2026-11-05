import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const WARN_RATIO = 0.75;
export const URGENT_RATIO = 0.9;

export function formatTokens(tokens: number): string {
	return tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens);
}

export function gaugeLine(tokens: number, contextWindow: number): string {
	const pct = Math.round((tokens / contextWindow) * 100);
	const where = `${formatTokens(tokens)}/${formatTokens(contextWindow)}`;
	if (pct >= Math.round(URGENT_RATIO * 100)) {
		return `[ctx ${pct}% ${where} ⚠ 越过90%紧迫线,当前工具批结束后立即用 compact 压缩(摘要带 fold-index)]`;
	}
	if (pct >= Math.round(WARN_RATIO * 100)) {
		return `[ctx ${pct}% ${where} 已越过75%建议线,在自然工作边界用 compact 压缩(摘要带 fold-index)]`;
	}
	return `[ctx ${pct}% ${where}]`;
}

export default async function (pi: ExtensionAPI) {
	let attachedThisTurn = false;
	pi.on("turn_start", () => {
		attachedThisTurn = false;
	});
	pi.on("tool_result", async (event, ctx) => {
		if (attachedThisTurn || event.isError) return;
		const usage = ctx.getContextUsage();
		if (!usage || usage.tokens == null) return;
		attachedThisTurn = true;
		if (ctx.hasUI) {
			ctx.ui.setStatus(
				"context-gauge",
				`ctx ${usage.percent ?? "?"}% ${formatTokens(usage.tokens)}/${formatTokens(usage.contextWindow)}`,
			);
		}
		const appended = [...event.content, { type: "text" as const, text: gaugeLine(usage.tokens, usage.contextWindow) }];
		return event.structuredContent === undefined
			? { content: appended }
			: { content: appended, structuredContent: event.structuredContent };
	});
	pi.on("turn_end", async (_event, ctx) => {
		if (!ctx.hasUI) return;
		const usage = ctx.getContextUsage();
		ctx.ui.setStatus(
			"context-gauge",
			usage && usage.percent !== null ? `ctx ${usage.percent}% ${formatTokens(usage.tokens ?? 0)}/${formatTokens(usage.contextWindow)}` : undefined,
		);
	});
}
