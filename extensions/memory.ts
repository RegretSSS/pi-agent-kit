import { appendFile, mkdir, readFile, readdir, rename, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const MEMORY_TYPES = ["user", "project", "feedback", "reference"] as const;
const INDEX_HEADING = "# Memory Index";
const FORBIDDEN_NAME = /[/\\\s:]|\.\.|[\x00-\x1f\x7f]/;
const FENCE_RE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
const SECTION_HEADING_RE = /^ {0,3}## +(.+?)\s*$/;
const SECTION_NAME_MAX_CHARS = 64;
const RULE_SHAPED = [/看到[^。\n]{1,40}就\s*(fail|拒绝|报错|禁)/, /(一律|必须|禁止|不得|不许)[^。\n]{0,40}(一律|必须|禁止|不得|不许)/];
const PROJECT_TTL_MS = 30 * 24 * 3600 * 1000;
const BODY_PREVIEW_CHARS = 600;
const CANDIDATES_MAX_BYTES = 5 * 1024 * 1024;
const CONTEXT_TOP_K = 30;
const DESCRIPTION_MAX_CHARS = 300;

export function normalizeName(name: string): string {
	return name.toLowerCase().normalize("NFC");
}
const LINT_TEMPLATE = [
	"这条是判定性知识(可写成「看到 X 就 fail」),不该进 memory。分流去 lints/:",
	"1. 在所在仓新建 lints/<rule_name>.py,一规则一文件,接入 scripts/run-lints.sh",
	"2. 结构约定 → pattern lint;行为语义 → behavioral lint(加载真模块 + 重放原始失败输入);跨端闭环 → E2E",
	"3. 提交后跑 gate(pytest + run-lints.sh)全绿",
	"若确认是描述性事实或判断题,调整 description/body 去掉规则腔后重试 memory_save",
].join("\n");

export type MemoryType = (typeof MEMORY_TYPES)[number];

export type MemoryEntry = {
	name: string;
	description: string;
	type: MemoryType;
	file: string;
	body: string;
	expiryAt?: string;
	archiveCandidate?: boolean;
};

export type SearchHit = { entry: MemoryEntry; termsHit: number };

export type SaveOptions = { mode?: "replace" | "append"; section?: string };

export type SaveOutcome =
	| { status: "saved"; entry: MemoryEntry; updated: boolean; merged?: "appended" | "section" }
	| { status: "rejected-lints"; message: string }
	| { status: "rejected-duplicate"; hits: SearchHit[] };

export type BodySection = { title: string; content: string };

export function splitSections(body: string): { preamble: string; sections: BodySection[] } {
	let openFence: string | null = null;
	const preambleLines: string[] = [];
	const sections: { title: string; lines: string[] }[] = [];
	let current: { title: string; lines: string[] } | null = null;
	for (const line of body.split("\n")) {
		const fence = FENCE_RE.exec(line);
		if (openFence !== null) {
			(current ? current.lines : preambleLines).push(line);
			if (fence && fence[1][0] === openFence[0] && fence[1].length >= openFence.length && !fence[2].trim()) openFence = null;
			continue;
		}
		if (fence) {
			openFence = fence[1];
			(current ? current.lines : preambleLines).push(line);
			continue;
		}
		const heading = SECTION_HEADING_RE.exec(line);
		if (heading) {
			current = { title: heading[1].trim(), lines: [] };
			sections.push(current);
			continue;
		}
		(current ? current.lines : preambleLines).push(line);
	}
	return {
		preamble: preambleLines.join("\n").trim(),
		sections: sections.map((section) => ({ title: section.title, content: section.lines.join("\n").trim() })),
	};
}

export function replaceSection(body: string, section: string, content: string): string {
	const parsed = splitSections(body);
	const trimmed = content.trim();
	const idx = parsed.sections.findIndex((candidate) => candidate.title === section);
	if (idx >= 0) parsed.sections[idx] = { title: section, content: trimmed };
	else parsed.sections.push({ title: section, content: trimmed });
	const parts: string[] = [];
	if (parsed.preamble) parts.push(parsed.preamble);
	for (const item of parsed.sections) {
		parts.push(item.content ? `## ${item.title}\n\n${item.content}` : `## ${item.title}`);
	}
	return parts.join("\n\n") + "\n";
}

export function appendBody(existing: string, addition: string): string {
	const trimmed = addition.trim();
	if (!trimmed) return existing.trim() + "\n";
	const base = existing.trim();
	return base ? `${base}\n\n${trimmed}\n` : `${trimmed}\n`;
}

export function isRuleShaped(text: string): boolean {
	return RULE_SHAPED.some((pattern) => pattern.test(text));
}

export function stripControlCodes(text: string): string {
	return text.replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
}

export function quoteFtsPhrase(term: string): string {
	return '"' + term.replaceAll('"', '""') + '"';
}

export function buildFtsQuery(terms: string[]): string {
	return terms.map(quoteFtsPhrase).join(" OR ");
}

export function splitTerms(query: string): string[] {
	return query.split(/\s+/).filter((term) => term.length >= 3);
}

export function parseFrontmatter(text: string, file: string): MemoryEntry | null {
	if (!text.startsWith("---\n")) return null;
	const end = text.indexOf("\n---\n", 4);
	if (end < 0) return null;
	const fields = new Map<string, string>();
	for (const line of text.slice(4, end).split("\n")) {
		const idx = line.indexOf(":");
		if (idx <= 0) continue;
		fields.set(line.slice(0, idx).trim(), line.slice(idx + 1).trim());
	}
	const name = fields.get("name");
	const description = fields.get("description");
	const type = fields.get("type");
	if (!name || !description || !MEMORY_TYPES.includes(type as MemoryType)) return null;
	return {
		name,
		description,
		type: type as MemoryType,
		file,
		body: text.slice(end + 5),
		expiryAt: fields.get("expiry_at") || undefined,
		archiveCandidate: fields.get("archive_candidate") === "true" || undefined,
	};
}

export function renderEntry(entry: MemoryEntry): string {
	const lines = ["---", `name: ${entry.name}`, `description: ${entry.description}`, `type: ${entry.type}`];
	if (entry.expiryAt) lines.push(`expiry_at: ${entry.expiryAt}`);
	if (entry.archiveCandidate) lines.push("archive_candidate: true");
	lines.push("---", "", entry.body.endsWith("\n") ? entry.body : entry.body + "\n");
	return lines.join("\n");
}

export function renderIndex(entries: MemoryEntry[]): string {
	const rows = [...entries]
		.sort((a, b) => a.name.localeCompare(b.name))
		.map((entry) => {
			const suffix = entry.archiveCandidate ? " (archive-candidate)" : "";
			return `- [${entry.name}](${entry.file}) — ${entry.description}${suffix}`;
		});
	return [INDEX_HEADING, "", ...rows].join("\n") + "\n";
}

type RefRow = { name: string; last_referenced: number };

export class MemoryStore {
	readonly root: string;
	private db: DatabaseSync | null = null;
	private entriesCache: MemoryEntry[] | null = null;
	private indexMtimeMs = 0;
	private dirMtimeMs = -1;
	private indexText: string | null = null;

	constructor(root?: string) {
		this.root = root ?? join(homedir(), ".agents", "memory");
	}

	private open(): DatabaseSync {
		if (this.db) return this.db;
		this.db = new DatabaseSync(join(this.root, ".index.db"));
		this.db.exec("PRAGMA journal_mode=WAL");
		this.db.exec("PRAGMA busy_timeout=3000");
		this.db.exec("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(name, description, body, tokenize='trigram')");
		this.db.exec("CREATE TABLE IF NOT EXISTS memory_refs (name TEXT PRIMARY KEY, last_referenced INTEGER NOT NULL)");
		return this.db;
	}

	close(): void {
		this.db?.close();
		this.db = null;
	}

	async listEntries(force = false): Promise<MemoryEntry[]> {
		if (!force && this.entriesCache) {
			if (await this.dirUnchanged()) return this.entriesCache;
		}
		const entries: MemoryEntry[] = [];
		await mkdir(this.root, { recursive: true });
		for (const name of await readdir(this.root)) {
			if (!name.endsWith(".md") || name === "MEMORY.md") continue;
			const parsed = parseFrontmatter(await readFile(join(this.root, name), "utf8"), name);
			if (parsed) entries.push(parsed);
		}
		this.entriesCache = entries;
		this.dirMtimeMs = await this.probeDirMtime();
		return entries;
	}

	private async probeDirMtime(): Promise<number> {
		try {
			return (await stat(this.root)).mtimeMs;
		} catch {
			return -1;
		}
	}

	private async dirUnchanged(): Promise<boolean> {
		if (this.dirMtimeMs < 0) return false;
		return (await this.probeDirMtime()) === this.dirMtimeMs;
	}

	async rebuildFts(): Promise<void> {
		const db = this.open();
		const entries = await this.listEntries(true);
		db.exec("BEGIN");
		try {
			db.exec("DROP TABLE IF EXISTS memory_fts");
			db.exec("CREATE VIRTUAL TABLE memory_fts USING fts5(name, description, body, tokenize='trigram')");
			const insert = db.prepare("INSERT INTO memory_fts(name, description, body) VALUES (?, ?, ?)");
			for (const entry of entries) insert.run(entry.name, entry.description, entry.body);
			db.exec("COMMIT");
		} catch (error) {
			db.exec("ROLLBACK");
			throw error;
		}
	}

	async rebuildIndex(): Promise<MemoryEntry[]> {
		const entries = await this.listEntries(true);
		await writeFile(join(this.root, "MEMORY.md"), renderIndex(entries), "utf8");
		this.indexText = null;
		try {
			await this.rebuildFts();
		} catch {}
		return entries;
	}

	ftsNames(terms: string[], columns: string[] = ["name", "description", "body"]): Set<string> {
		if (terms.length === 0) return new Set();
		const db = this.open();
		const prefix = columns.length > 0 ? `{${columns.join(" ")}} : ` : "";
		const rows = db.prepare("SELECT name FROM memory_fts WHERE memory_fts MATCH ?").all(prefix + buildFtsQuery(terms)) as { name: string }[];
		return new Set(rows.map((row) => row.name));
	}

	countTermHits(entry: MemoryEntry, terms: string[], rawQuery: string): number {
		const haystackName = entry.name.toLowerCase();
		const haystackDesc = entry.description.toLowerCase();
		let hits = 0;
		for (const term of terms) {
			const lower = term.toLowerCase();
			const nameHit = haystackName.includes(lower) || (haystackName.length >= 5 && lower.includes(haystackName));
			const descHit = haystackDesc.includes(lower) || (haystackDesc.length >= 5 && lower.includes(haystackDesc));
			if (nameHit || descHit) hits += 1;
		}
		if (rawQuery && (haystackName.includes(rawQuery) || haystackDesc.includes(rawQuery))) hits += terms.length;
		return hits;
	}

	async search(query: string, topK: number): Promise<SearchHit[]> {
		const rawQuery = query.trim().toLowerCase();
		const terms = splitTerms(query);
		const ftsHit = this.ftsNames(terms);
		const entries = await this.listEntries();
		const hits: SearchHit[] = [];
		for (const entry of entries) {
			const termHits = this.countTermHits(entry, terms, rawQuery);
			const ftsMatched = ftsHit.has(entry.name);
			if (ftsMatched || termHits > 0) hits.push({ entry, termsHit: termHits + (ftsMatched ? terms.length : 0) });
		}
		hits.sort((a, b) => b.termsHit - a.termsHit || a.entry.name.localeCompare(b.entry.name));
		const top = hits.slice(0, topK);
		if (top.length > 0) await this.markReferenced(top.map((hit) => hit.entry.name));
		return top;
	}

	async save(name: string, description: string, type: string, body: string, options: SaveOptions = {}): Promise<SaveOutcome> {
		const mode = options.mode ?? "replace";
		if (mode !== "replace" && mode !== "append") {
			return { status: "rejected-lints", message: "mode 必须是 replace/append" };
		}
		let section: string | undefined;
		if (options.section !== undefined) {
			if (mode === "append") {
				return { status: "rejected-lints", message: "section 与 mode=append 互斥:给 section 即小节级替换,不做整体追加" };
			}
			section = stripControlCodes(options.section).trim();
			if (!section || section.length > SECTION_NAME_MAX_CHARS || section.includes("#")) {
				return { status: "rejected-lints", message: `section 需为非空小节名(≤${SECTION_NAME_MAX_CHARS} 字符,不含 #),层级由工具补` };
			}
		}
		if (type === "problem" || isRuleShaped(`${description}\n${body}`)) {
			return { status: "rejected-lints", message: LINT_TEMPLATE };
		}
		if (!(MEMORY_TYPES as readonly string[]).includes(type)) {
			return { status: "rejected-lints", message: `type 必须是 ${MEMORY_TYPES.join("/")};判定性知识请去 lints/` };
		}
		if (!name || name.length > 64 || FORBIDDEN_NAME.test(name) || name.toLowerCase() === "memory") {
			return { status: "rejected-lints", message: "name 需为短 slug(无空白/路径分隔符,≤64 字符,不得为 MEMORY)" };
		}
		if (description.includes("\n") || description.includes("\r")) {
			return { status: "rejected-lints", message: "description 必须单行(它是 frontmatter 字段与索引行);细节放进 body" };
		}
		const cleanDescription = stripControlCodes(description).trim();
		if (!cleanDescription) {
			return { status: "rejected-lints", message: "description 不能为空或纯控制字符" };
		}
		if (cleanDescription.length > DESCRIPTION_MAX_CHARS) {
			return { status: "rejected-lints", message: `description 上限 ${DESCRIPTION_MAX_CHARS} 字符,细节放进 body` };
		}
		description = cleanDescription;
		const normalizedName = normalizeName(name);
		const entries = await this.listEntries();
		const existing = entries.find((entry) => normalizeName(entry.name) === normalizedName);
		if (!existing) {
			const query = `${name} ${description}`;
			const duplicates = (await this.findDuplicates(query, entries, ["name", "description"])).filter(
				(hit) => hit.termsHit >= 2 || (normalizeName(hit.entry.name).length >= 5 && (normalizedName.includes(normalizeName(hit.entry.name)) || normalizeName(hit.entry.name).includes(normalizedName))),
			);
			if (duplicates.length > 0) {
				return { status: "rejected-duplicate", hits: duplicates.slice(0, 3) };
			}
		}
		const expiryAt = type === "project" ? new Date(Date.now() + PROJECT_TTL_MS).toISOString() : undefined;
		const canonicalName = existing ? existing.name : name;
		const canonicalFile = existing ? existing.file : `${name}.md`;
		let mergedBody = body;
		let merged: "appended" | "section" | undefined;
		if (existing) {
			if (mode === "append") {
				mergedBody = appendBody(existing.body, body);
				merged = "appended";
			} else if (section) {
				mergedBody = replaceSection(existing.body, section, body);
				merged = "section";
			}
		} else if (section) {
			mergedBody = replaceSection("", section, body);
		}
		const entry: MemoryEntry = { name: canonicalName, description, type: type as MemoryType, file: canonicalFile, body: mergedBody, expiryAt };
		await writeFile(join(this.root, entry.file), renderEntry(entry), "utf8");
		this.entriesCache = null;
		await this.rebuildIndex();
		return { status: "saved", entry, updated: Boolean(existing), merged };
	}

	async findDuplicates(query: string, entries: MemoryEntry[], columns: string[] = ["name", "description", "body"]): Promise<SearchHit[]> {
		const terms = splitTerms(query);
		const rawQuery = query.trim().toLowerCase();
		const ftsHit = this.ftsNames(terms, columns);
		const duplicates: SearchHit[] = [];
		for (const entry of entries) {
			const termHits = this.countTermHits(entry, terms, rawQuery);
			if (ftsHit.has(entry.name) || termHits > 0) duplicates.push({ entry, termsHit: termHits });
		}
		duplicates.sort((a, b) => b.termsHit - a.termsHit);
		return duplicates;
	}

	async markReferenced(names: string[]): Promise<void> {
		const db = this.open();
		const now = Date.now();
		const upsert = db.prepare("INSERT INTO memory_refs(name, last_referenced) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET last_referenced = excluded.last_referenced");
		for (const name of names) upsert.run(name, now);
	}

	async scanArchiveCandidates(): Promise<MemoryEntry[]> {
		const db = this.open();
		const now = Date.now();
		const entries = await this.listEntries();
		const refs = new Map((db.prepare("SELECT name, last_referenced FROM memory_refs").all() as RefRow[]).map((row) => [row.name, row.last_referenced]));
		const promoted: MemoryEntry[] = [];
		for (const entry of entries) {
			if (!entry.expiryAt || entry.archiveCandidate) continue;
			const expiry = Date.parse(entry.expiryAt);
			if (Number.isNaN(expiry) || expiry > now) continue;
			const lastRef = refs.get(entry.name) ?? 0;
			if (lastRef >= expiry) continue;
			entry.archiveCandidate = true;
			await writeFile(join(this.root, entry.file), renderEntry(entry), "utf8");
			promoted.push(entry);
		}
		if (promoted.length > 0) await this.rebuildIndex();
		return promoted;
	}

	async appendCandidateRecord(record: unknown): Promise<void> {
		await mkdir(this.root, { recursive: true });
		const path = join(this.root, ".candidates.jsonl");
		try {
			const info = await stat(path);
			if (info.size > CANDIDATES_MAX_BYTES) await rename(path, `${path}.1`);
		} catch {}
		await appendFile(path, JSON.stringify(record) + "\n", "utf8");
	}

	renderContextIndex(entries: MemoryEntry[]): string {
		const header = `持久跨会话记忆可用。下方为高频条目(共 ${entries.length} 条);未列出条目与正文用 memory_search 按需检索,不要凭空假设没有。`;
		const refs = new Map((this.open().prepare("SELECT name, last_referenced FROM memory_refs").all() as RefRow[]).map((row) => [row.name, row.last_referenced]));
		const ranked = [...entries].sort((a, b) => {
			const ra = refs.get(a.name) ?? 0;
			const rb = refs.get(b.name) ?? 0;
			if (ra !== rb) return rb - ra;
			return a.name.localeCompare(b.name);
		});
		const shown = ranked.slice(0, CONTEXT_TOP_K);
		const rows = shown.map((entry) => `- [${entry.type}] ${entry.name} — ${entry.description}`);
		if (ranked.length > shown.length) {
			rows.push(`(其余 ${ranked.length - shown.length} 条略,用 memory_search 检索)`);
		}
		return [header, "", ...rows].join("\n");
	}

	async contextIndexText(): Promise<string | null> {
		const indexPath = join(this.root, "MEMORY.md");
		let info;
		try {
			info = await stat(indexPath);
		} catch {
			return null;
		}
		if (this.indexMtimeMs === info.mtimeMs && this.indexText !== null) return this.indexText;
		this.indexMtimeMs = info.mtimeMs;
		this.indexText = this.renderContextIndex(await this.listEntries());
		return this.indexText;
	}
}

function formatHits(hits: SearchHit[]): string {
	return hits
		.map((hit, i) => {
			const preview = stripControlCodes(hit.entry.body.slice(0, BODY_PREVIEW_CHARS).replace(/\s+/g, " "));
			return `${i + 1}. [${hit.entry.type}] ${hit.entry.name} — ${hit.entry.description}\n   path: ~/.agents/memory/${hit.entry.file}\n   ${preview}`;
		})
		.join("\n");
}

export default async function (pi: ExtensionAPI) {
	const { Type } = await import("typebox");
	const { StringEnum } = await import("@earendil-works/pi-ai");
	const store = new MemoryStore();
	let toolErrors: { tool: string; message: string }[] = [];
	let tokensIn = 0;
	let tokensOut = 0;

	pi.registerTool({
		name: "memory_save",
		label: "Memory Save",
		description: "持久化一条跨会话记忆。判定性知识(看到 X 就 fail 的规则)禁止入内,会被分流到 lints/。name 命中已有条目时支持增量更新:mode=append 追加段落,section 替换/新建命名小节;未命中则新建。",
		promptSnippet: "跨会话记忆的查重新建/增量更新",
		promptGuidelines: ["Use memory_save for durable cross-session facts and judgments; rules that can fail mechanically belong in lints/ instead."],
		parameters: Type.Object({
			name: Type.String({ description: "短 slug,kebab-case,作为文件名" }),
			description: Type.String({ description: "一行钩子,进 MEMORY.md 索引;命中已有条目时也会覆盖此字段" }),
			type: StringEnum([...MEMORY_TYPES, "problem"] as const),
			body: Type.String({ description: "replace 模式为正文全文;append 模式为追加的段落;给了 section 则为该小节的新内容" }),
			mode: Type.Optional(StringEnum(["replace", "append"] as const)),
			section: Type.Optional(Type.String({ description: "命名小节(## 标题):存在则替换该节,不存在则尾插;与 mode=append 互斥" })),
		}),
		async execute(_toolCallId, params) {
			const outcome = await store.save(params.name, params.description, params.type, params.body, { mode: params.mode, section: params.section });
			if (outcome.status === "rejected-lints") {
				return { content: [{ type: "text", text: outcome.message }], details: { status: outcome.status }, isError: true };
			}
			if (outcome.status === "rejected-duplicate") {
				const lines = ["疑似重复,拒绝新建。已有相近条目:", formatHits(outcome.hits), "要更新就在 memory_save 里用旧条目的 name 覆盖(或 mode=append/section 增量);确属新条目请改 name/description 后重试。"];
				return { content: [{ type: "text", text: lines.join("\n") }], details: { status: outcome.status, hits: outcome.hits.map((hit) => hit.entry.name) }, isError: true };
			}
			let verb: string;
			if (!outcome.updated) verb = "saved";
			else if (outcome.merged === "appended") verb = "appended to";
			else if (outcome.merged === "section") verb = `updated section "${params.section}" of`;
			else verb = "updated";
			return {
				content: [{ type: "text", text: `${verb} ${outcome.entry.name} (${outcome.entry.type});MEMORY.md 索引已重建` }],
				details: { status: outcome.status, name: outcome.entry.name, file: outcome.entry.file, merged: outcome.merged ?? null },
			};
		},
	});

	pi.registerTool({
		name: "memory_search",
		label: "Memory Search",
		description: "FTS5 trigram 全文检索跨会话记忆,中文/子串友好,返回 top_k 条。",
		promptSnippet: "跨会话记忆检索",
		promptGuidelines: ["Use memory_search before re-deriving facts that earlier sessions may have memorized."],
		parameters: Type.Object({
			query: Type.String({ description: "检索词,中文或英文" }),
			top_k: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
		}),
		async execute(_toolCallId, params) {
			const hits = await store.search(params.query, params.top_k ?? 5);
			if (hits.length === 0) {
				return { content: [{ type: "text", text: "无命中" }], details: { hits: [] } };
			}
			return { content: [{ type: "text", text: formatHits(hits) }], details: { hits: hits.map((hit) => hit.entry.name) } };
		},
	});

	pi.on("session_start", async (_event, ctx) => {
		await store.rebuildIndex();
		const promoted = await store.scanArchiveCandidates();
		if (promoted.length > 0 && ctx.hasUI) {
			ctx.ui.notify(`memory: ${promoted.length} 条过期未引用条目标为归档候选`, "info");
		}
	});

	pi.on("before_agent_start", async (event) => {
		const index = await store.contextIndexText();
		if (!index) return;
		event.systemPromptOptions.sections["agent-memory-index"] = index;
	});

	pi.on("tool_execution_end", async (event) => {
		if (!event.isError) return;
		const content = event.result?.content;
		const firstText = Array.isArray(content) ? content.find((part) => part?.type === "text") : undefined;
		toolErrors.push({ tool: event.toolName, message: String((firstText as { text?: string } | undefined)?.text ?? "").slice(0, 200) });
	});

	pi.on("message_end", async (event) => {
		if (event.message.role !== "assistant") return;
		const usage = event.message.usage;
		if (!usage) return;
		tokensIn += usage.input ?? 0;
		tokensOut += usage.output ?? 0;
	});

	pi.on("agent_settled", async (_event, ctx) => {
		if (toolErrors.length === 0 && tokensIn === 0 && tokensOut === 0) return;
		const record = {
			ts: new Date().toISOString(),
			session: ctx.sessionManager.getSessionFile(),
			tool_errors: toolErrors,
			tokens: { in: tokensIn, out: tokensOut },
		};
		toolErrors = [];
		tokensIn = 0;
		tokensOut = 0;
		await store.appendCandidateRecord(record);
	});

	pi.on("session_shutdown", async () => {
		store.close();
	});
}
