#!/usr/bin/env node
import { mkdir, readdir, readFile, rename, rm, stat, cp } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";

const globalRoot = join(homedir(), ".agents", "memory");
const bucketFor = (name) => {
	if (/^(backend-|cc-)/.test(name)) return "EngAssistantBackend";
	if (/^aicontest-/.test(name)) return "aicontest-clinical-note";
	return null;
};
const apply = process.argv.includes("--apply");
const backup = join(homedir(), ".agents", "memory.bak-d19");

const { MemoryStore } = await import(new URL("../extensions/memory.ts", import.meta.url).pathname);
const store = new MemoryStore(globalRoot);
const entries = await store.listEntries(true);
store.close();

const misplaced = entries.filter((e) => e.type === "project");
const plan = [];
const unmapped = [];
for (const entry of misplaced) {
	const bucket = bucketFor(entry.name);
	if (!bucket) unmapped.push(entry.name);
	else plan.push({ name: entry.name, file: entry.file, from: globalRoot, to: join(globalRoot, "projects", `-home-remedy-workspace-${bucket}`) });
}

console.log(`global 桶 ${entries.length} 条,其中 type: project ${misplaced.length} 条`);
for (const row of plan) console.log(`  ${row.name} -> ${row.to}`);
for (const name of unmapped) console.log(`  未映射(留在 global): ${name}`);
if (!apply) {
	console.log("\n dry-run:加 --apply 执行(将先备份到 " + backup + ")");
	process.exit(0);
}

if (unmapped.length > 0 && !process.argv.includes("--allow-unmapped")) {
	console.error(`有 ${unmapped.length} 条未映射,先补 bucketFor 规则或加 --allow-unmapped(只移已映射条目)`);
	process.exit(1);
}
try {
	await stat(backup);
	console.log(`备份已存在,跳过: ${backup}`);
} catch {
	await cp(globalRoot, backup, { recursive: true });
	console.log(`已备份: ${backup}`);
}

const touched = new Set(plan.map((row) => row.to));
for (const row of plan) {
	await mkdir(row.to, { recursive: true });
	await rename(join(row.from, row.file), join(row.to, row.file));
	console.log(`moved ${row.file}`);
}
touched.add(globalRoot);
for (const root of touched) {
	const target = new MemoryStore(root);
	await target.rebuildIndex();
	target.close();
	console.log(`rebuildIndex: ${root}`);
}
console.log(`完成:迁移 ${plan.length} 条,未动 ${unmapped.length} 条`);
