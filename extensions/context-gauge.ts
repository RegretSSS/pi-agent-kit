import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const WARN_RATIO = 0.75;
export const URGENT_RATIO = 0.9;
export const REPORT_INTERVAL_MS = 15 * 60 * 1000;
export const PCT_BUCKET = 0.05;

export function formatTokens(tokens: number): string {
	return tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens);
}

export function clockLine(now = new Date()): string {
	const pad = (n: number) => String(n).padStart(2, "0");
	const week = ["日", "一", "二", "三", "四", "五", "六"][now.getDay()];
	const offsetHours = -now.getTimezoneOffset() / 60;
	const tz = `UTC${offsetHours >= 0 ? "+" : ""}${Number.isInteger(offsetHours) ? offsetHours : offsetHours.toFixed(1)}`;
	return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())} 周${week}(${tz})`;
}

export function gaugeLine(tokens: number, contextWindow: number, now = new Date()): string {
	const pct = Math.round((tokens / contextWindow) * 100);
	const where = `${formatTokens(tokens)}/${formatTokens(contextWindow)}`;
	const clock = clockLine(now);
	if (pct >= Math.round(URGENT_RATIO * 100)) {
		return `[ctx ${pct}% ${where} ⚠ 越过90%紧迫线,当前工具批结束后立即用 compact 压缩(摘要带 fold-index) | ${clock}]`;
	}
	if (pct >= Math.round(WARN_RATIO * 100)) {
		return `[ctx ${pct}% ${where} 已越过75%建议线,在自然工作边界用 compact 压缩(摘要带 fold-index) | ${clock}]`;
	}
	return `[ctx ${pct}% ${where} | ${clock}]`;
}

export function shouldReport(tokens: number, contextWindow: number, lastReportAt: number, lastTier: number, lastBucket: number, nowMs: number): { report: boolean; tier: number; bucket: number } {
	const ratio = tokens / contextWindow;
	const tier = ratio >= URGENT_RATIO ? 2 : ratio >= WARN_RATIO ? 1 : 0;
	const bucket = Math.floor(ratio / PCT_BUCKET);
	const due = nowMs - lastReportAt >= REPORT_INTERVAL_MS;
	const bucketCrossed = tier === 0 && bucket !== lastBucket;
	const highWaterAlways = tier >= 1;
	return { report: due || bucketCrossed || highWaterAlways || tier > lastTier, tier, bucket };
}

export default async function (pi: ExtensionAPI) {
	let lastReportAt = 0;
	let lastTier = 0;
	let lastBucket = -1;
	pi.on("session_start", async () => {
		lastReportAt = 0;
		lastTier = 0;
		lastBucket = -1;
	});
	pi.on("session_compact", async () => {
		lastReportAt = 0;
		lastTier = 0;
		lastBucket = -1;
	});
	pi.on("tool_result", async (event, ctx) => {
		const usage = ctx.getContextUsage();
		if (!usage || usage.tokens == null) return;
		if (ctx.hasUI) {
			ctx.ui.setStatus(
				"context-gauge",
				`ctx ${usage.percent ?? "?"}% ${formatTokens(usage.tokens)}/${formatTokens(usage.contextWindow)} | ${clockLine()}`,
			);
		}
		const nowMs = Date.now();
		const gate = shouldReport(usage.tokens, usage.contextWindow, lastReportAt, lastTier, lastBucket, nowMs);
		if (!gate.report) return;
		lastReportAt = nowMs;
		lastTier = gate.tier;
		lastBucket = gate.bucket;
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
			usage && usage.percent !== null ? `ctx ${usage.percent}% ${formatTokens(usage.tokens ?? 0)}/${formatTokens(usage.contextWindow)} | ${clockLine()}` : undefined,
		);
	});
}
