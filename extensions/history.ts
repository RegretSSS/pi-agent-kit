import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const PREVIEW_RADIUS = 120;
const PREVIEW_FALLBACK = 160;
const WINDOW_RADIUS = 500;
export const OUTLINE_BUDGET = 4000;
const READ_BUDGET = 8000;
const DEFAULT_LIMIT = 5;
const CJK = /[一-鿿]/;

export type BlockRow = {
	session: string;
	blockId: string;
	ord: number;
	tier: number;
	topic: string;
	startSeq: number;
	endSeq: number;
	tokens: number;
	summary: string;
};

export type ScoredBlock = { row: BlockRow; score: number; hitTerms: string[] };

function defaultDbPath(): string {
	return join(homedir(), ".local/share/billion-context/sessions/index.db");
}

function defaultSidecarDir(): string {
	return join(homedir(), ".agents/history");
}

export function splitTerms(query: string): string[] {
	return query.toLowerCase().split(/\s+/).filter((t) => t.length > 0);
}

export function bigrams(term: string): string[] {
	const out: string[] = [];
	for (let i = 0; i + 2 <= term.length; i += 1) out.push(term.slice(i, i + 2));
	return out;
}

export function scoreRow(row: BlockRow, terms: string[]): ScoredBlock | null {
	if (terms.length === 0) return null;
	const haystack = (row.topic + "\n" + row.summary).toLowerCase();
	const hitTerms: string[] = [];
	let score = 0;
	for (const term of terms) {
		if (haystack.includes(term)) {
			hitTerms.push(term);
			score += 1;
			continue;
		}
		if (term.length >= 4 && CJK.test(term)) {
			const grams = bigrams(term);
			const hit = grams.filter((g) => haystack.includes(g)).length;
			if (grams.length > 0 && hit / grams.length >= 0.5) {
				hitTerms.push(term);
				score += 0.5;
			}
		}
	}
	if (hitTerms.length === 0) return null;
	if (row.topic.toLowerCase().split(/\s+/).some((w) => hitTerms.some((t) => w.includes(t)))) score += 0.5;
	return { row, score, hitTerms };
}

export function windowAround(text: string, term: string, radius: number): string {
	const lower = text.toLowerCase();
	const idx = lower.indexOf(term.toLowerCase());
	if (idx === -1) return text.slice(0, radius * 2);
	const start = Math.max(0, idx - radius);
	const end = Math.min(text.length, idx + term.length + radius);
	return (start > 0 ? "…" : "") + text.slice(start, end) + (end < text.length ? "…" : "");
}

export function mergeWindows(text: string, terms: string[], radius: number): string {
	const lower = text.toLowerCase();
	const spans: Array<[number, number]> = [];
	for (const term of terms) {
		let idx = lower.indexOf(term.toLowerCase());
		while (idx !== -1) {
			spans.push([Math.max(0, idx - radius), Math.min(text.length, idx + term.length + radius)]);
			idx = lower.indexOf(term.toLowerCase(), idx + term.length);
		}
	}
	if (spans.length === 0) return text.slice(0, radius * 2);
	spans.sort((a, b) => a[0] - b[0]);
	const merged: Array<[number, number]> = [];
	for (const span of spans) {
		const last = merged[merged.length - 1];
		if (last && span[0] <= last[1]) last[1] = Math.max(last[1], span[1]);
		else merged.push([...span] as [number, number]);
	}
	return merged.map(([s, e]) => (s > 0 ? "…" : "") + text.slice(s, e) + (e < text.length ? "…" : "")).join("\n…\n");
}

export function formatOutline(hits: ScoredBlock[], budget: number): { text: string; truncated: number } {
	const lines: string[] = [];
	let used = 0;
	let truncated = 0;
	for (const hit of hits) {
		const row = hit.row;
		const head = `[${row.blockId}] ${row.session.slice(0, 8)} · ${row.topic} · ${row.summary.length}ch m${row.startSeq}-m${row.endSeq}`;
		const preview = "  " + (hit.hitTerms.length > 0 ? windowAround(row.summary, hit.hitTerms[0], PREVIEW_RADIUS) : row.summary.slice(0, PREVIEW_FALLBACK));
		const block = head + "\n" + preview;
		if (used + block.length > budget) {
			truncated = hits.length - lines.length / 2;
			break;
		}
		used += block.length;
		lines.push(head, preview);
	}
	const suffix = truncated > 0 ? `\n[truncated ${truncated} blocks — refine the query]` : "";
	const drill = lines.length > 0 ? `\ndrill: history_read(session, block, around="term")` : "";
	return { text: `${lines.join("\n")}${suffix}${drill}`, truncated };
}

export class HistoryIndex {
	private readonly dbPath: string;
	private readonly sidecarDir: string;
	private signature = "";
	private rows: BlockRow[] | null = null;
	private available = false;

	constructor(dbPath = defaultDbPath(), sidecarDir = defaultSidecarDir()) {
		this.dbPath = dbPath;
		this.sidecarDir = sidecarDir;
	}

	private sidecarPath(): string {
		return join(this.sidecarDir, "sidecar.jsonl");
	}

	isAvailable(): boolean {
		return this.available;
	}

	private async loadSidecar(): Promise<BlockRow[]> {
		const text = await readFile(this.sidecarPath(), "utf8");
		return text.split("\n").filter((l) => l.trim().length > 0).map((l) => JSON.parse(l) as BlockRow);
	}

	private async persistSidecar(rows: BlockRow[]): Promise<void> {
		await mkdir(this.sidecarDir, { recursive: true });
		const tmp = join(this.sidecarDir, "sidecar.tmp");
		await writeFile(tmp, rows.map((r) => JSON.stringify(r)).join("\n") + "\n", "utf8");
		await rename(tmp, this.sidecarPath());
	}

	private readBlocks(): BlockRow[] {
		const db = new DatabaseSync(this.dbPath);
		db.exec("PRAGMA busy_timeout = 3000");
		const out: BlockRow[] = [];
		try {
			const rows = db.prepare("SELECT session_id, block_id, ord, tier, start_seq, end_seq, payload_json FROM blocks ORDER BY session_id, ord").all() as Array<Record<string, unknown>>;
			for (const r of rows) {
				let payload: Record<string, unknown>;
				try {
					payload = JSON.parse(String(r.payload_json)) as Record<string, unknown>;
				} catch {
					continue;
				}
				out.push({
					session: String(r.session_id),
					blockId: String(r.block_id),
					ord: Number(r.ord),
					tier: Number(r.tier),
					topic: typeof payload.topic === "string" ? payload.topic : "",
					startSeq: Number(r.start_seq),
					endSeq: Number(r.end_seq),
					tokens: Number(payload.compressedTokens ?? 0),
					summary: typeof payload.summary === "string" ? payload.summary : "",
				});
			}
		} finally {
			db.close();
		}
		return out;
	}

	async refresh(): Promise<boolean> {
		let signature = "";
		try {
			const s = await stat(this.dbPath);
			signature = `${s.mtimeMs}:${s.size}`;
		} catch {
			if (this.rows !== null) return true;
			try {
				this.rows = await this.loadSidecar();
				this.available = true;
				return true;
			} catch {
				this.available = false;
				return false;
			}
		}
		if (signature === this.signature && this.rows !== null) return true;
		try {
			this.rows = this.readBlocks();
			this.signature = signature;
			this.available = true;
			await this.persistSidecar(this.rows);
			return true;
		} catch {
			if (this.rows !== null) return true;
			try {
				this.rows = await this.loadSidecar();
				this.available = true;
				return true;
			} catch {
				this.available = false;
				return false;
			}
		}
	}

	async search(query: string, session?: string, limit = DEFAULT_LIMIT): Promise<ScoredBlock[]> {
		if (!(await this.refresh()) || this.rows === null) return [];
		const terms = splitTerms(query);
		const pool = session ? this.rows.filter((r) => r.session === session || r.session.startsWith(session)) : this.rows;
		return pool.map((r) => scoreRow(r, terms)).filter((s): s is ScoredBlock => s !== null).sort((a, b) => b.score - a.score).slice(0, limit);
	}

	async readBlock(session: string, block: string, around?: string): Promise<string | null> {
		if (!(await this.refresh()) || this.rows === null) return null;
		const row = this.rows.find((r) => (r.session === session || r.session.startsWith(session)) && r.blockId === block);
		if (!row) return null;
		if (!around) return row.summary.slice(0, READ_BUDGET);
		const terms = splitTerms(around);
		if (terms.length === 0) return row.summary.slice(0, READ_BUDGET);
		const text = mergeWindows(row.summary, terms, WINDOW_RADIUS);
		return text.length > READ_BUDGET ? text.slice(0, READ_BUDGET) + "…" : text;
	}
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	const index = new HistoryIndex();

	pi.registerTool({
		name: "history_search",
		label: "History Search",
		description: [
			"Search compressed-history block summaries from billion-context across ALL sessions (cross-session recall).",
			"Returns an outline only: one line + short preview per block, hard budget — refine the query or drill with history_read.",
			"Works even after compact (sidecar snapshot). Calling convention: in code-mode harnesses call via the generated SDK and consume details structurally.",
		].join(" "),
		parameters: Type.Object({
			query: Type.String({ description: "检索词,空格分隔多词(中文长词会自动降级为二字滑窗匹配)" }),
			session: Type.Optional(Type.String({ description: "可选,限定会话 id(前缀匹配)" })),
			limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 10 })),
		}),
		async execute(_toolCallId, params) {
			if (!(await index.refresh())) {
				return {
					content: [{ type: "text", text: "history index unavailable: billion-context database not found and no sidecar snapshot exists. Fallback: grep ~/.pi/agent/sessions/*/<session>.jsonl" }],
					details: { available: false, hits: [] },
				};
			}
			const hits = await index.search(params.query, params.session, params.limit ?? DEFAULT_LIMIT);
			if (hits.length === 0) {
				return { content: [{ type: "text", text: "无命中。换更短的关键词,或用 history_read 直接读已知块。" }], details: { available: true, hits: [] } };
			}
			const outline = formatOutline(hits, OUTLINE_BUDGET);
			return {
				content: [{ type: "text", text: `${hits.length} block(s) match:\n${outline.text}` }],
				details: { available: true, hits: hits.map((h) => ({ session: h.row.session, block: h.row.blockId, topic: h.row.topic, score: h.score, hitTerms: h.hitTerms })), truncated: outline.truncated },
			};
		},
	});

	pi.registerTool({
		name: "history_read",
		label: "History Read",
		description: "Read one compressed-history block. With `around`: only keyword-centered windows (cheap). Without: the full block summary (budgeted). Calling convention: in code-mode harnesses call via the generated SDK.",
		parameters: Type.Object({
			session: Type.String({ description: "会话 id(前缀匹配)" }),
			block: Type.String({ description: "块 id,如 b3" }),
			around: Type.Optional(Type.String({ description: "关键词,只取其 ±500 字符窗口" })),
		}),
		async execute(_toolCallId, params) {
			const text = await index.readBlock(params.session, params.block, params.around);
			if (text === null) {
				return { content: [{ type: "text", text: "块不存在或 history 不可用。用 history_search 先定位。" }], details: { found: false }, isError: true };
			}
			return { content: [{ type: "text", text }], details: { found: true, session: params.session, block: params.block } };
		},
	});
}
