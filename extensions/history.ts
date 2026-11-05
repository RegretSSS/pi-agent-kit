import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const PREVIEW_RADIUS = 120;
const PREVIEW_FALLBACK = 160;
const WINDOW_RADIUS = 500;
const OUTLINE_BUDGET = 4000;
const OUTLINE_SLACK = 140;
const READ_BUDGET = 8000;
const DEFAULT_LIMIT = 5;
const MAX_LIMIT = 10;
const SESSION_ID_RADIUS = 18;
const TOPIC_BUDGET = 80;
const CJK = /[一-鿿]/;

let instanceCounter = 0;

export type BlockRow = {
	session: string;
	blockId: string;
	ord: number;
	tier: number;
	active: boolean;
	topic: string;
	startSeq: number;
	endSeq: number;
	tokens: number;
	summary: string;
};

export type ScoredBlock = { row: BlockRow; score: number; hitTerms: string[] };

export type ReadOutcome =
	| { status: "ok"; text: string; row: BlockRow }
	| { status: "missing" }
	| { status: "ambiguous"; candidates: Array<{ session: string; topic: string }> }
	| { status: "invalid-session" }
	| { status: "unavailable" };

export type TypeBoxLike = {
	Object: (schema: Record<string, unknown>) => unknown;
	String: (opts?: Record<string, unknown>) => unknown;
	Optional: (schema: unknown) => unknown;
	Integer: (opts?: Record<string, unknown>) => unknown;
};

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

export function rowHaystack(row: BlockRow): string {
	return (row.topic + "\n" + row.summary).toLowerCase();
}

export function scoreRow(row: BlockRow, terms: string[], hay = rowHaystack(row)): ScoredBlock | null {
	if (terms.length === 0) return null;
	const hitTerms: string[] = [];
	let score = 0;
	for (const term of terms) {
		if (hay.includes(term)) {
			hitTerms.push(term);
			score += 1;
			continue;
		}
		if (term.length >= 4 && CJK.test(term)) {
			const grams = bigrams(term);
			const hit = grams.filter((g) => hay.includes(g)).length;
			if (grams.length > 0 && hit / grams.length >= 0.5) {
				hitTerms.push(term);
				score += 0.5;
			}
		}
	}
	if (hitTerms.length === 0) return null;
	const topicLower = row.topic.toLowerCase();
	if (hitTerms.some((t) => topicLower.includes(t))) score += 0.5;
	return { row, score, hitTerms };
}

export function windowAround(text: string, term: string, radius: number): string {
	const idx = text.toLowerCase().indexOf(term.toLowerCase());
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
	let shown = 0;
	let truncated = 0;
	for (const hit of hits) {
		const row = hit.row;
		const flag = row.active ? "" : "|inactive";
		const head = `[${row.blockId}${flag}] ${row.session.slice(0, SESSION_ID_RADIUS)} · ${row.topic.slice(0, TOPIC_BUDGET)} · ${row.summary.length}ch m${row.startSeq}-m${row.endSeq}`;
		const inSummary = hit.hitTerms.find((t) => row.summary.toLowerCase().includes(t));
		const preview = "  " + (inSummary ? windowAround(row.summary, inSummary, PREVIEW_RADIUS) : row.summary.slice(0, PREVIEW_FALLBACK));
		const block = head + "\n" + preview;
		if (used + block.length + OUTLINE_SLACK > budget) {
			truncated = hits.length - shown;
			break;
		}
		used += block.length;
		lines.push(head, preview);
		shown += 1;
	}
	const suffix = truncated > 0 ? `\n[truncated ${truncated} blocks — refine the query]` : "";
	const drill = shown > 0 ? "\ndrill: history_read(session=<full id from details>, block, around=\"term\")" : "";
	return { text: `${lines.join("\n")}${suffix}${drill}`, truncated };
}

export class HistoryIndex {
	private readonly dbPath: string;
	private readonly sidecarDir: string;
	private signature = "";
	private lastPayload = "";
	private rows: BlockRow[] | null = null;
	private available = false;
	private origin: "db" | "sidecar" = "sidecar";
	private readonly hayCache = new Map<string, string>();
	private epoch = 0;
	private persistFailed = false;
	private readonly instanceId = (instanceCounter += 1);
	private persistMu: Promise<void> = Promise.resolve();

	constructor(dbPath = defaultDbPath(), sidecarDir = defaultSidecarDir()) {
		this.dbPath = dbPath;
		this.sidecarDir = sidecarDir;
	}

	private sidecarPath(): string {
		return this.sidecarFile();
	}

	isAvailable(): boolean {
		return this.available;
	}

	source(): "db" | "sidecar" {
		return this.origin;
	}

	private hay(row: BlockRow): string {
		const key = `${row.session}/${row.blockId}`;
		let value = this.hayCache.get(key);
		if (value === undefined) {
			value = rowHaystack(row);
			this.hayCache.set(key, value);
		}
		return value;
	}

	private parseSidecar(text: string): BlockRow[] {
		const rows: BlockRow[] = [];
		for (const line of text.split("\n")) {
			if (line.trim().length === 0) continue;
			try {
				const parsed = JSON.parse(line) as Record<string, unknown>;
				if (typeof parsed.session !== "string" || typeof parsed.summary !== "string") continue;
				rows.push({
					session: parsed.session,
					blockId: String(parsed.blockId ?? ""),
					ord: Number(parsed.ord ?? 0),
					tier: Number(parsed.tier ?? 1),
					active: parsed.active !== false,
					topic: typeof parsed.topic === "string" ? parsed.topic : "",
					startSeq: Number(parsed.startSeq ?? 0),
					endSeq: Number(parsed.endSeq ?? 0),
					tokens: Number(parsed.tokens ?? 0),
					summary: parsed.summary,
				});
			} catch {
				continue;
			}
		}
		return rows;
	}

	private async loadSidecar(): Promise<BlockRow[]> {
		let entries: string[];
		try {
			entries = await readdir(this.sidecarDir);
		} catch {
			return [];
		}
		const candidates: Array<{ name: string; mtime: number }> = [];
		for (const name of [...entries]) {
			if (name !== "sidecar.jsonl" && !/^sidecar\.\d+(\.\d+)?\.jsonl$/.test(name)) continue;
			try {
				const s = await stat(join(this.sidecarDir, name));
				candidates.push({ name, mtime: s.mtimeMs });
			} catch {
			}
		}
		candidates.sort((a, b) => b.mtime - a.mtime);
		for (const { name } of candidates) {
			try {
				const text = await readFile(join(this.sidecarDir, name), "utf8");
				const rows = this.parseSidecar(text);
				if (rows.length > 0) return rows;
			} catch {
			}
		}
		return [];
	}

	private sidecarFile(): string {
		return join(this.sidecarDir, `sidecar.${process.pid}.${this.instanceId}.jsonl`);
	}

	private async doPersist(rows: BlockRow[]): Promise<void> {
		await mkdir(this.sidecarDir, { recursive: true });
		const tmp = join(this.sidecarDir, `sidecar.${process.pid}.${this.instanceId}.tmp`);
		await writeFile(tmp, rows.map((r) => JSON.stringify(r)).join("\n") + "\n", "utf8");
		await rename(tmp, this.sidecarFile());
		await this.sweepStaleSnapshots();
	}

	private async persistSidecar(rows: BlockRow[]): Promise<void> {
		const run = this.persistMu.then(() => this.doPersist(rows));
		this.persistMu = run.catch(() => {});
		await run;
	}

	private async sweepStaleSnapshots(): Promise<void> {
		try {
			const entries = await readdir(this.sidecarDir);
			const cutoff = Date.now() - 7200_000;
			for (const name of entries) {
				if (!/^sidecar\.\d+(\.\d+)?\.jsonl$/.test(name)) continue;
				const full = join(this.sidecarDir, name);
				if (full === this.sidecarFile()) continue;
				try {
					const s = await stat(full);
					if (s.mtimeMs >= cutoff) continue;
					const again = await stat(full);
					if (again.mtimeMs >= cutoff) continue;
					await rm(full, { force: true });
				} catch {
				}
			}
		} catch {
		}
	}

	private openDb(): DatabaseSync {
		const db = new DatabaseSync(this.dbPath);
		db.exec("PRAGMA busy_timeout = 3000");
		return db;
	}

	private readBlocks(): BlockRow[] {
		const db = this.openDb();
		const out: BlockRow[] = [];
		try {
			const rows = db.prepare("SELECT session_id, block_id, ord, tier, active, start_seq, end_seq, payload_json FROM blocks ORDER BY session_id, ord").all() as Array<Record<string, unknown>>;
			for (const r of rows) {
				try {
					const payload = JSON.parse(String(r.payload_json)) as Record<string, unknown>;
					if (payload === null || typeof payload !== "object") continue;
					const topic = typeof payload.topic === "string" ? payload.topic : "";
					const summary = typeof payload.summary === "string" ? payload.summary : "";
					if (topic.length === 0 && summary.length === 0) continue;
					out.push({
						session: String(r.session_id),
						blockId: String(r.block_id),
						ord: Number(r.ord ?? 0),
						tier: Number(r.tier ?? 1),
						active: Number(r.active ?? 1) === 1,
						topic,
						startSeq: Number(r.start_seq ?? 0),
						endSeq: Number(r.end_seq ?? 0),
						tokens: Number(payload.compressedTokens ?? 0),
						summary,
					});
				} catch {
					continue;
				}
			}
		} finally {
			db.close();
		}
		if (out.length === 0) throw new Error("blocks table empty or unreadable");
		return out;
	}

	private async currentSignature(): Promise<string | null> {
		const parts: string[] = [];
		for (const p of [this.dbPath, `${this.dbPath}-wal`]) {
			try {
				const s = await stat(p);
				parts.push(`${s.mtimeMs}:${s.size}`);
			} catch {
				if (p === this.dbPath) return null;
			}
		}
		try {
			const db = this.openDb();
			try {
				const counted = db.prepare("SELECT COUNT(*) AS n FROM blocks").get() as { n: number };
				parts.push(`rows:${counted.n}`);
			} finally {
				db.close();
			}
		} catch {
			return null;
		}
		return parts.join("|");
	}

	async refresh(): Promise<boolean> {
		const epoch = ++this.epoch;
		const signature = await this.currentSignature();
		if (epoch !== this.epoch) return this.available;
		if (signature === null) return this.fallback(epoch);
		if (signature === this.signature && this.rows !== null && !this.persistFailed) return true;
		try {
			const rows = this.readBlocks();
			if (epoch !== this.epoch) return this.available;
			this.rows = rows;
			this.signature = signature;
			this.available = true;
			this.origin = "db";
			this.hayCache.clear();
			const payload = rows.map((r) => JSON.stringify(r)).join("\n");
			if (payload !== this.lastPayload) {
				try {
					await this.persistSidecar(rows);
					if (epoch !== this.epoch) return this.available;
					this.lastPayload = payload;
					this.persistFailed = false;
				} catch (err) {
					if (epoch !== this.epoch) return this.available;
					this.persistFailed = true;
					console.error(`history sidecar persist failed (serving fresh db data): ${err instanceof Error ? err.message : String(err)}`);
				}
			}
			return true;
		} catch {
			return this.fallback(epoch);
		}
	}

	private async fallback(epoch: number): Promise<boolean> {
		if (this.rows !== null) {
			this.available = true;
			return true;
		}
		try {
			const rows = await this.loadSidecar();
			if (epoch !== this.epoch) return this.available;
			if (rows.length === 0) {
				this.available = false;
				return false;
			}
			this.rows = rows;
			this.available = true;
			this.origin = "sidecar";
			this.hayCache.clear();
			return true;
		} catch {
			if (epoch !== this.epoch) return this.available;
			this.available = false;
			return false;
		}
	}

	async search(query: string, session?: string, limit = DEFAULT_LIMIT): Promise<ScoredBlock[]> {
		if (!(await this.refresh()) || this.rows === null) return [];
		const terms = splitTerms(query);
		const scope = session?.trim();
		const pool = scope && scope.length > 0 ? this.rows.filter((r) => r.session === scope || r.session.startsWith(scope)) : this.rows;
		return pool.map((r) => scoreRow(r, terms, this.hay(r))).filter((s): s is ScoredBlock => s !== null).sort((a, b) => b.score - a.score).slice(0, Math.max(1, Math.min(limit, MAX_LIMIT)));
	}

	async readBlock(session: string, block: string, around?: string): Promise<ReadOutcome> {
		if (!(await this.refresh()) || this.rows === null) return { status: "unavailable" };
		const scope = (session ?? "").trim();
		if (scope.length < 4) return { status: "invalid-session" };
		const matches = this.rows.filter((r) => (r.session === scope || r.session.startsWith(scope)) && r.blockId === block);
		if (matches.length === 0) return { status: "missing" };
		const sessions = [...new Set(matches.map((m) => m.session))];
		if (sessions.length > 1) {
			return { status: "ambiguous", candidates: matches.map((m) => ({ session: m.session, topic: m.topic })) };
		}
		const row = matches[0];
		let text: string;
		if (!around) text = row.summary.slice(0, READ_BUDGET);
		else {
			const terms = splitTerms(around);
			if (terms.length === 0) text = row.summary.slice(0, READ_BUDGET);
			else {
				const merged = mergeWindows(row.summary, terms, WINDOW_RADIUS);
				text = merged.length > READ_BUDGET ? merged.slice(0, READ_BUDGET) + "…" : merged;
			}
		}
		return { status: "ok", text, row };
	}
}

export function buildTools(Type: TypeBoxLike, index: HistoryIndex) {
	const searchTool = {
		name: "history_search",
		label: "History Search",
		description: [
			"Search compressed-history block summaries from billion-context across ALL sessions (cross-session recall).",
			"Returns an outline only: one line + short preview per block, hard budget — refine the query or drill with history_read.",
			"Works even after compact (sidecar snapshot). Blocks marked |inactive belong to superseded epochs of a session.",
			"Calling convention: in code-mode harnesses call via tools.history_search(...); the text result is line-structured (one block per two lines) and safe to parse.",
		].join(" "),
		parameters: Type.Object({
			query: Type.String({ description: "检索词,空格分隔多词(中文长词会自动降级为二字滑窗匹配)" }),
			session: Type.Optional(Type.String({ description: "可选,限定会话 id(前缀匹配)" })),
			limit: Type.Optional(Type.Integer({ minimum: 1, maximum: MAX_LIMIT })),
		}),
		async execute(_toolCallId: string, params: { query: string; session?: string; limit?: number }) {
			const hits = await index.search(params.query, params.session, params.limit ?? DEFAULT_LIMIT);
			if (!index.isAvailable()) {
				return {
					content: [{ type: "text", text: "history index unavailable: billion-context database not found and no sidecar snapshot exists. Fallback: grep ~/.pi/agent/sessions/*/<session>.jsonl" }],
					details: { available: false, hits: [] },
					isError: true,
				};
			}
			if (hits.length === 0) {
				return { content: [{ type: "text", text: "无命中。换更短的关键词,或用 history_read 直接读已知块。" }], details: { available: true, source: index.source(), hits: [] } };
			}
			const outline = formatOutline(hits, OUTLINE_BUDGET);
			return {
				content: [{ type: "text", text: `${hits.length} block(s) match:\n${outline.text}` }],
				details: {
					available: true,
					source: index.source(),
					truncated: outline.truncated,
					hits: hits.map((h) => ({ session: h.row.session, block: h.row.blockId, active: h.row.active, topic: h.row.topic.slice(0, TOPIC_BUDGET), score: h.score, hitTerms: h.hitTerms })),
				},
			};
		},
	};
	const readTool = {
		name: "history_read",
		label: "History Read",
		description: "Read one compressed-history block. Pass the FULL session id (from history_search details) — short prefixes that match several sessions are rejected with candidates. With `around`: only keyword-centered windows (cheap). Without: the full block summary (budgeted). Calling convention: in code-mode harnesses call via tools.history_read(...); the text result is the block content.",
		parameters: Type.Object({
			session: Type.String({ description: "完整会话 id(或足够长的唯一前缀,≥4 字符)" }),
			block: Type.String({ description: "块 id,如 b3" }),
			around: Type.Optional(Type.String({ description: "关键词,只取其 ±500 字符窗口" })),
		}),
		async execute(_toolCallId: string, params: { session: string; block: string; around?: string }) {
			const outcome = await index.readBlock(params.session, params.block, params.around);
			if (outcome.status === "unavailable") {
				return { content: [{ type: "text", text: "history index unavailable: no database and no sidecar snapshot. Fallback: grep ~/.pi/agent/sessions/*/<session>.jsonl" }], details: { status: outcome.status }, isError: true };
			}
			if (outcome.status === "invalid-session") {
				return { content: [{ type: "text", text: "session 参数无效:传完整会话 id或 ≥4 字符的唯一前缀(空/超短前缀会横跨多个会话)。" }], details: { status: outcome.status }, isError: true };
			}
			if (outcome.status === "missing") {
				return { content: [{ type: "text", text: "块不存在。用 history_search 先定位。" }], details: { status: outcome.status }, isError: true };
			}
			if (outcome.status === "ambiguous") {
				const list = outcome.candidates.map((c) => `- ${c.session} · ${c.topic.slice(0, TOPIC_BUDGET)}`).join("\n");
				return { content: [{ type: "text", text: `会话前缀歧义,该 blockId 命中多个会话,请用完整 id 重试:\n${list}` }], details: { status: outcome.status, candidates: outcome.candidates }, isError: true };
			}
			return { content: [{ type: "text", text: outcome.text }], details: { status: "ok", source: index.source(), session: outcome.row.session, block: outcome.row.blockId, active: outcome.row.active } };
		},
	};
	return [searchTool, readTool];
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	const index = new HistoryIndex();
	for (const tool of buildTools(Type, index)) pi.registerTool(tool);
}
