import { MemoryStore, ScopedMemory, projectMemoryRoot } from "../extensions/memory.ts";

const [root, scenario, payload] = process.argv.slice(2);
const store = new MemoryStore(root);
const out = {};

switch (scenario) {
	case "save": {
		const p = JSON.parse(payload);
		const outcome = await store.save(p.name, p.description, p.type, p.body, { mode: p.mode, section: p.section });
		out.outcome = { status: outcome.status, updated: outcome.updated ?? null, merged: outcome.merged ?? null, hits: outcome.hits?.map((h) => h.entry.name) ?? null, message: outcome.message?.slice(0, 200) ?? null };
		break;
	}
	case "read": {
		const p = JSON.parse(payload);
		const entry = (await store.listEntries(true)).find((e) => e.name === p.name);
		out.body = entry?.body ?? null;
		out.archiveCandidate = entry?.archiveCandidate ?? false;
		break;
	}
	case "search": {
		const p = JSON.parse(payload);
		const hits = await store.search(p.query, p.top_k ?? 5);
		out.names = hits.map((h) => h.entry.name);
		break;
	}
	case "index": {
		out.index = await store.contextIndexText();
		out.entries = (await store.listEntries(true)).map((e) => ({ name: e.name, type: e.type, expiryAt: e.expiryAt ?? null, archiveCandidate: e.archiveCandidate ?? false }));
		break;
	}
	case "render-context": {
		const fake = Array.from({ length: 35 }, (_, i) => ({ name: "n" + i, description: "d" + i, type: "reference", file: `n${i}.md`, body: "b" }));
		out.rendered = store.renderContextIndex(fake);
		break;
	}
	case "backdate": {
		const p = JSON.parse(payload);
		const { readFile, writeFile } = await import("node:fs/promises");
		const file = `${root}/${p.name}.md`;
		const text = await readFile(file, "utf8");
		await writeFile(file, text.replace(/^expiry_at: .*$/m, `expiry_at: 2000-01-01T00:00:00.000Z`), "utf8");
		out.ok = true;
		break;
	}
	case "archive-scan": {
		const p = JSON.parse(payload);
		const { DatabaseSync } = await import("node:sqlite");
		const db = new DatabaseSync(`${root}/.index.db`);
		db.prepare("INSERT OR REPLACE INTO memory_refs(name, last_referenced) VALUES (?, ?)").run(p.name, p.lastReferenced);
		db.close();
		out.promoted = (await store.scanArchiveCandidates()).map((e) => e.name);
		break;
	}
	case "candidates": {
		await store.appendCandidateRecord({ probe: true });
		out.ok = true;
		break;
	}
	case "candidates-rotate": {
		const fsp = await import("node:fs/promises");
		await fsp.writeFile(`${root}/.candidates.jsonl`, "x".repeat(5 * 1024 * 1024 + 1), "utf8");
		await store.appendCandidateRecord({ after: "rotate" });
		out.rotated = (await fsp.stat(`${root}/.candidates.jsonl.1`)).size > 5 * 1024 * 1024;
		out.fresh = await fsp.readFile(`${root}/.candidates.jsonl`, "utf8");
		break;
	}
	case "project-root": {
		const p = JSON.parse(payload);
		out.root = projectMemoryRoot(p.cwd, p.globalRoot ?? root);
		break;
	}
	case "scoped": {
		const p = JSON.parse(payload);
		const mem = new ScopedMemory(root, p.projectRoot);
		if (p.action === "save") {
			const outcome = await mem.save(p.name, p.description, p.type, p.body, { scope: p.scope });
			out.outcome = { status: outcome.status, message: outcome.message?.slice(0, 200) ?? null };
		} else if (p.action === "search") {
			const hits = await mem.search(p.query, p.top_k ?? 5, p.scope);
			out.hits = hits.map((h) => ({ name: h.entry.name, scope: h.scope, root: h.root, termsHit: h.termsHit }));
			out.text = hits.map((h, i) => `${i + 1}. [${h.scope}] ${h.entry.name} @ ${h.root}`).join("\n");
		} else if (p.action === "context") {
			out.text = await mem.mergedContextText();
		} else if (p.action === "maintenance") {
			out.promoted = (await mem.sessionMaintenance()).map((e) => e.name);
		}
		mem.close();
		break;
	}
	default:
		throw new Error(`unknown scenario: ${scenario}`);
}

store.close();
console.log(JSON.stringify(out));
