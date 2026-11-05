import { DatabaseSync } from "node:sqlite";
import { rm, readFile, mkdir, chmod, utimes, writeFile } from "node:fs/promises";
import { HistoryIndex, formatOutline, scoreRow, splitTerms, buildTools } from "../extensions/history.ts";
import { buildCompactInstructions } from "../extensions/compact-tool.ts";

const [root, scenario, payload] = process.argv.slice(2);
const dbPath = `${root}/bili.db`;
const sidecarDir = `${root}/sidecar`;
const out = {};

const fakeType = {
	Object: (o) => o,
	String: (o) => ({ kind: "string", ...o }),
	Optional: (s) => ({ kind: "optional", of: s }),
	Integer: (o) => ({ kind: "integer", ...o }),
};

function seedDb() {
	const db = new DatabaseSync(dbPath);
	db.exec("CREATE TABLE blocks (session_id TEXT, block_id TEXT, ord INTEGER, tier INTEGER, active INTEGER, start_seq INTEGER, end_seq INTEGER, payload_json TEXT)");
	const mk = (session, blockId, ord, active, start, end, topic, summary, tokens) =>
		db.prepare("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)").run(
			session, blockId, ord, 1, active, start, end,
			JSON.stringify({ blockId, tier: 1, topic, summary, compressedTokens: tokens }),
		);
	mk("01a1a774-48cc", "b1", 0, 1, 0, 82, "整理ClaudeCode记忆入memory系统", "用户指令:整理之前ClaudeCode在这个仓库工作时的记忆,列入记忆系统。".repeat(3), 55647);
	mk("01a1a774-48cc", "b2", 1, 1, 83, 129, "夜间深挖第一轮:新规范载体pi-agent-kit", "夜间深挖。民法典重灌状态从待核实测为已闭环,dev库127.0.0.1:15432。", 28965);
	mk("01a1a784-b231", "b1", 0, 1, 0, 40, "git log 页1", "只读分析全部1370 commit,按月聚合。", 1200);
	mk("01a1a784-b23c", "b1", 0, 1, 0, 40, "docs 探索启动", "docs 目录第一轮探索,民法典在册件替换重灌。", 900);
	mk("01a1a94b-7621", "b2", 1, 0, 41, 90, "民法典重灌状态实测闭环(旧代)", "重灌状态实测闭环,71号2017已换A10正式件。", 800);
	db.close();
}

function seedBig() {
	const db = new DatabaseSync(dbPath);
	db.exec("CREATE TABLE blocks (session_id TEXT, block_id TEXT, ord INTEGER, tier INTEGER, active INTEGER, start_seq INTEGER, end_seq INTEGER, payload_json TEXT)");
	const stmt = db.prepare("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)");
	for (let i = 0; i < 14; i += 1) {
		stmt.run(`sess${i}`, `b${i}`, 0, 1, 1, 0, 9, JSON.stringify({ blockId: `b${i}`, tier: 1, topic: `批次${i}巡检`, summary: `第${i}批巡检发现民法典重灌相关线索${i}号`, compressedTokens: 100 }));
	}
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
	case "seed-big": {
		seedBig();
		const idx = new HistoryIndex(dbPath, sidecarDir);
		out.refreshed = await idx.refresh();
		break;
	}
	case "search": {
		const { query, session, limit } = JSON.parse(payload);
		const idx = new HistoryIndex(dbPath, sidecarDir);
		const hits = await idx.search(query, session, limit ?? 5);
		out.hits = hits.map((h) => ({ block: h.row.blockId, session: h.row.session, active: h.row.active, score: h.score }));
		break;
	}
	case "search-bigram": {
		const idx = new HistoryIndex(dbPath, sidecarDir);
		out.hits = (await idx.search("民法典重灌状态")).map((h) => h.row.blockId);
		break;
	}
	case "outline-budget": {
		const blocks = Array.from({ length: 20 }, (_, i) => ({ session: "s" + i, blockId: "b" + i, ord: i, tier: 1, active: true, topic: "bulk" + i, startSeq: 0, endSeq: 9, tokens: 1, summary: "关键词".repeat(1500) }));
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
		const outcome = await idx.readBlock(session, block, around);
		out.status = outcome.status;
		if (outcome.status === "ok") {
			out.session = outcome.row.session;
			out.active = outcome.row.active;
			out.text = outcome.text.slice(0, 300);
		}
		if (outcome.status === "ambiguous") out.candidates = outcome.candidates;
		break;
	}
	case "execute-search": {
		const { query, limit } = JSON.parse(payload);
		const idx = new HistoryIndex(dbPath, sidecarDir);
		const [tool] = buildTools(fakeType, idx);
		const r = await tool.execute("t1", { query, limit });
		out.textHead = r.content[0].text.slice(0, 120);
		out.source = r.details.source ?? null;
		out.hits = (r.details.hits ?? []).map((h) => ({ session: h.session, topicLen: (h.topic ?? "").length, active: h.active }));
		out.truncated = r.details.truncated ?? null;
		break;
	}
	case "persist-fail": {
		seedDb();
		const { writeFile } = await import("node:fs/promises");
		const blocked = `${root}/blocked-dir`;
		await writeFile(blocked, "occupied");
		const idx = new HistoryIndex(dbPath, blocked);
		out.refreshed = await idx.refresh();
		out.available = idx.isAvailable();
		out.source = idx.source();
		out.hits = (await idx.search("民法典")).map((h) => h.row.blockId);
		break;
	}
	case "execute-read": {
		const { session, block } = JSON.parse(payload);
		const idx = new HistoryIndex(dbPath, sidecarDir);
		const [, tool] = buildTools(fakeType, idx);
		const r = await tool.execute("t1", { session, block });
		out.isError = r.isError === true;
		out.head = r.content[0].text.slice(0, 160);
		out.details = r.details;
		break;
	}
	case "execute-unavailable": {
		const idx = new HistoryIndex(`${root}/nope.db`, `${root}/no-sidecar`);
		const [tool] = buildTools(fakeType, idx);
		const r = await tool.execute("t1", { query: "x" });
		out.available = r.details.available;
		out.text = r.content[0].text.slice(0, 120);
		break;
	}
	case "empty-table": {
		seedDb();
		const first = new HistoryIndex(dbPath, sidecarDir);
		await first.refresh();
		const { join } = await import("node:path");
		const { readdir: ls } = await import("node:fs/promises");
		const pick = async () => (await ls(sidecarDir)).filter((n) => n.endsWith(".jsonl")).sort()[0];
		const before = await readFile(join(sidecarDir, await pick()), "utf8");
		const db = new DatabaseSync(dbPath);
		db.exec("PRAGMA busy_timeout = 3000");
		db.exec("DELETE FROM blocks");
		db.close();
		const second = new HistoryIndex(dbPath, sidecarDir);
		out.refreshed = await second.refresh();
		out.available = second.isAvailable();
		out.sidecarUnchanged = (await readFile(join(sidecarDir, await pick()), "utf8")) === before;
		break;
	}
	case "shrink": {
		seedDb();
		const first = new HistoryIndex(dbPath, sidecarDir);
		await first.refresh();
		const db = new DatabaseSync(dbPath);
		db.exec("PRAGMA busy_timeout = 3000");
		db.exec("DELETE FROM blocks WHERE session_id LIKE '01a1a77%' OR session_id LIKE '01a1a78%'");
		db.close();
		const second = new HistoryIndex(dbPath, sidecarDir);
		out.refreshed = await second.refresh();
		await rm(dbPath, { force: true });
		const third = new HistoryIndex(dbPath, sidecarDir);
		await third.refresh();
		const all = await third.search("民法典");
		out.sessions = [...new Set(all.map((h) => h.row.session))];
		out.count = all.length;
		out.source = third.source();
		break;
	}
	case "ro-sidecar": {
		seedDb();
		const roDir = `${root}/ro-sidecar`;
		await mkdir(roDir, { recursive: true });
		await chmod(roDir, 0o555);
		const idx = new HistoryIndex(dbPath, roDir);
		const startedAt = Date.now();
		out.refreshed = await idx.refresh();
		out.elapsedMs = Date.now() - startedAt;
		out.available = idx.isAvailable();
		out.source = idx.source();
		out.hits = (await idx.search("民法典")).map((h) => h.row.blockId);
		await chmod(roDir, 0o755);
		break;
	}
	case "multi-snapshot": {
		const dir = `${root}/multi`;
		await mkdir(dir, { recursive: true });
		const older = ["s-old", "b1", 0, 1, 1, true, "旧主题", 0, 5, 100, "旧内容"].join("\u0000");
		const lineOld = JSON.stringify({ session: "s-old", blockId: "b1", ord: 0, tier: 1, active: true, topic: "旧主题", startSeq: 0, endSeq: 5, tokens: 100, summary: "旧内容" });
		const lineNew = JSON.stringify({ session: "s-new", blockId: "b1", ord: 0, tier: 1, active: true, topic: "新主题", startSeq: 0, endSeq: 5, tokens: 100, summary: "新内容民法典" });
		await writeFile(`${dir}/sidecar.111.jsonl`, lineOld + "\n");
		await writeFile(`${dir}/sidecar.222.jsonl`, lineNew + "\n");
		const past = new Date(Date.now() - 60000);
		const recent = new Date(Date.now() - 1000);
		await utimes(`${dir}/sidecar.111.jsonl`, past, past);
		await utimes(`${dir}/sidecar.222.jsonl`, recent, recent);
		const idx = new HistoryIndex(`${root}/nope.db`, dir);
		out.refreshed = await idx.refresh();
		out.source = idx.source();
		out.sessions = (await idx.search("民法典")).map((h) => h.row.session);
		break;
	}
	case "staggered-race": {
		const { mkdir: warmMk, writeFile: warmWf } = await import("node:fs/promises");
		const { join: warmJoin } = await import("node:path");
		await warmMk(sidecarDir, { recursive: true });
		await warmWf(warmJoin(sidecarDir, "warm.tmp"), "x");
		const db = new DatabaseSync(dbPath);
		db.exec("CREATE TABLE blocks (session_id TEXT, block_id TEXT, ord INTEGER, tier INTEGER, active INTEGER, start_seq INTEGER, end_seq INTEGER, payload_json TEXT)");
		const stmt = db.prepare("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)");
		for (let i = 0; i < 60; i += 1) {
			stmt.run(`oldsess-${i}`, "b1", 0, 1, 1, 0, 9, JSON.stringify({ blockId: "b1", tier: 1, topic: `旧代${i}`, compressedTokens: 1, summary: "旧正文".repeat(4000) + `标记${i}` }));
		}
		db.close();
		const idx = new HistoryIndex(dbPath, sidecarDir);
		const first = idx.refresh();
		await new Promise((r) => setTimeout(r, 2));
		const db2 = new DatabaseSync(dbPath);
		db2.exec("PRAGMA busy_timeout = 3000");
		db2.exec("DELETE FROM blocks");
		const stmt2 = db2.prepare("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)");
		for (let i = 0; i < 5; i += 1) {
			stmt2.run(`newsess-${i}`, "b1", 0, 1, 1, 0, 9, JSON.stringify({ blockId: "b1", tier: 1, topic: `新代${i}`, compressedTokens: 1, summary: "新正文".repeat(4000) + `标记${i}` }));
		}
		db2.close();
		const second = idx.refresh();
		const results = await Promise.all([first, second]);
		const ok = results.some(Boolean);
		const { readdir: ls, readFile: rf } = await import("node:fs/promises");
		const { join: j } = await import("node:path");
		const files = (await ls(sidecarDir)).filter((n) => n.endsWith(".jsonl"));
		const perFile = [];
		for (const name of files) {
			const text = await rf(j(sidecarDir, name), "utf8");
			const lines = text.split("\n").filter((l) => l.trim().length > 0);
			let parsed = 0;
			const generations = new Set();
			for (const line of lines) {
				try {
					const row = JSON.parse(line);
				 parsed += 1;
					generations.add(row.session.startsWith("oldsess") ? "old" : "new");
				} catch {
					generations.add("broken");
				}
			}
			perFile.push({ lines: lines.length, parsed, generations: [...generations] });
		}
		await rm(dbPath, { force: true });
		const survivor = new HistoryIndex(dbPath, sidecarDir);
		await survivor.refresh();
		const fbHits = await survivor.search("新正文");
		out.ok = ok;
		out.results = results;
		out.files = perFile;
		out.fallbackSource = survivor.source();
		out.fallbackSessions = [...new Set(fbHits.map((h) => h.row.session))];
		break;
	}
	case "sweep": {
		seedDb();
		const dir = `${root}/sweepdir`;
		await mkdir(dir, { recursive: true });
		const three = new Date(Date.now() - 10800_000);
		const one = new Date(Date.now() - 3600_000);
		await writeFile(`${dir}/sidecar.111.1.jsonl`, "{}\n");
		await writeFile(`${dir}/sidecar.222.2.jsonl`, "{}\n");
		await writeFile(`${dir}/sidecar.333.3.tmp`, "{}\n");
		await utimes(`${dir}/sidecar.111.1.jsonl`, three, three);
		await utimes(`${dir}/sidecar.222.2.jsonl`, one, one);
		await utimes(`${dir}/sidecar.333.3.tmp`, three, three);
		const idx = new HistoryIndex(dbPath, dir);
		await idx.refresh();
		const names = (await (await import("node:fs/promises")).readdir(dir)).sort();
		out.remaining = names;
		break;
	}
	case "two-instances": {
		seedDb();
		const a = new HistoryIndex(dbPath, sidecarDir);
		const b = new HistoryIndex(dbPath, sidecarDir);
		await a.refresh();
		await b.refresh();
		const { readdir: ls } = await import("node:fs/promises");
		out.jsonlCount = (await ls(sidecarDir)).filter((n) => n.endsWith(".jsonl")).length;
		break;
	}
	case "stale": {
		await rm(dbPath, { force: true });
		const idx = new HistoryIndex(dbPath, sidecarDir);
		out.refreshed = await idx.refresh();
		out.available = idx.isAvailable();
		out.source = idx.source();
		out.hits = (await idx.search("民法典")).map((h) => h.row.blockId);
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
