import { DatabaseSync } from "node:sqlite";
import { rm } from "node:fs/promises";
import { HistoryIndex, formatOutline, scoreRow, splitTerms } from "../extensions/history.ts";
import { buildCompactInstructions } from "../extensions/compact-instructions.ts";

const [root, scenario, payload] = process.argv.slice(2);
const dbPath = `${root}/bili.db`;
const sidecarDir = `${root}/sidecar`;
const out = {};

function seedDb() {
	const db = new DatabaseSync(dbPath);
	db.exec("CREATE TABLE blocks (session_id TEXT, block_id TEXT, ord INTEGER, tier INTEGER, start_seq INTEGER, end_seq INTEGER, payload_json TEXT)");
	const mk = (session, blockId, ord, start, end, topic, summary, tokens) =>
		db.prepare("INSERT INTO blocks VALUES (?,?,?,?,?,?,?)").run(
			session, blockId, ord, 1, start, end,
			JSON.stringify({ blockId, tier: 1, topic, summary, compressedTokens: tokens, directMessageIds: [], effectiveMessageIds: [] }),
		);
	mk("01a1a774-48cc", "b1", 0, 0, 82, "整理ClaudeCode记忆入memory系统", "用户指令:整理之前ClaudeCode在这个仓库工作时的记忆,列入记忆系统。当前会话是普通交互式pi会话。".repeat(3), 55647);
	mk("01a1a774-48cc", "b2", 1, 83, 129, "夜间深挖第一轮:新规范载体pi-agent-kit", "夜间深挖,用户要求多了解项目。民法典重灌状态从待核实测为已闭环,dev库127.0.0.1:15432。", 28965);
	mk("01a1a94b-7621", "b1", 0, 0, 40, "看mailbox里都有谁", "调用mail_who查看了所有agent状态。", 1200);
	mk("01a1a94b-7621", "b2", 1, 41, 90, "民法典重灌状态实测闭环", "重灌状态实测闭环,生产71号2017已于10-26换A10正式件重灌285chunks。", 800);
	db.close();
}

switch (scenario) {
	case "seed": {
		seedDb();
		const idx = new HistoryIndex(dbPath, sidecarDir);
		out.refreshed = await idx.refresh();
		out.available = idx.isAvailable();
		break;
	}
	case "search": {
		const { query, session, limit } = JSON.parse(payload);
		const idx = new HistoryIndex(dbPath, sidecarDir);
		const hits = await idx.search(query, session, limit ?? 5);
		out.hits = hits.map((h) => ({ block: h.row.blockId, session: h.row.session, score: h.score, hitTerms: h.hitTerms }));
		break;
	}
	case "search-bigram": {
		const idx = new HistoryIndex(dbPath, sidecarDir);
		const hits = await idx.search("民法典重灌状态");
		out.hits = hits.map((h) => h.row.blockId);
		break;
	}
	case "outline-budget": {
		const blocks = Array.from({ length: 20 }, (_, i) => ({ session: "s" + i, blockId: "b" + i, ord: i, tier: 1, topic: "bulk" + i, startSeq: 0, endSeq: 9, tokens: 1, summary: "关键词".repeat(1500) }));
		const terms = splitTerms("关键词");
		const scored = blocks.map((b) => scoreRow(b, terms)).filter(Boolean);
		const formatted = formatOutline(scored, 600);
		out.length = formatted.text.length;
		out.truncated = formatted.truncated;
		break;
	}
	case "read": {
		const { session, block, around } = JSON.parse(payload);
		const idx = new HistoryIndex(dbPath, sidecarDir);
		const text = await idx.readBlock(session, block, around);
		out.text = text === null ? null : text.slice(0, 300);
		out.isNull = text === null;
		break;
	}
	case "stale": {
		await rm(dbPath, { force: true });
		const idx = new HistoryIndex(dbPath, sidecarDir);
		out.refreshed = await idx.refresh();
		out.available = idx.isAvailable();
		const hits = await idx.search("民法典");
		out.hits = hits.map((h) => h.row.blockId);
		break;
	}
	case "unavailable": {
		const idx = new HistoryIndex(`${root}/nope.db`, `${root}/no-sidecar`);
		out.refreshed = await idx.refresh();
		out.available = idx.isAvailable();
		break;
	}
	case "instructions": {
		const { brief, historyActive } = JSON.parse(payload);
		out.text = buildCompactInstructions(brief, historyActive);
		break;
	}
}

console.log(JSON.stringify(out));
