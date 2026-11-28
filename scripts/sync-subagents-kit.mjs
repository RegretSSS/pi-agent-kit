import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

const PKG = process.env.PI_SUBAGENTS_PKG ?? join(homedir(), ".pi/agent/npm/node_modules/@tintinweb/pi-subagents");
const KIT = process.env.PI_SUBAGENTS_KIT ?? join(homedir(), "workspace/pi-subagents-kit");
const BRANCH = process.env.PI_SUBAGENTS_KIT_BRANCH ?? "kit";

function kitGit(...args) {
	return execFileSync("git", ["-C", KIT, ...args], { encoding: "utf8" }).trim();
}

function sameTree(left, right) {
	const listed = (dir) => readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name));
	const leftEntries = listed(left);
	const rightEntries = listed(right);
	if (leftEntries.length !== rightEntries.length) return false;
	return leftEntries.every((entry, index) => {
		const other = rightEntries[index];
		if (entry.name !== other.name || entry.isDirectory() !== other.isDirectory()) return false;
		const mine = join(left, entry.name);
		const theirs = join(right, other.name);
		return entry.isDirectory() ? sameTree(mine, theirs) : readFileSync(mine).equals(readFileSync(theirs));
	});
}

function main() {
	const manifestPath = join(PKG, "package.json");
	if (!existsSync(manifestPath)) {
		console.log(`sync-subagents-kit: ${PKG} 没有 pi-subagents,跳过`);
		return 0;
	}
	const installed = JSON.parse(readFileSync(manifestPath, "utf8")).version;
	const baseline = JSON.parse(kitGit("show", `${BRANCH}:package.json`)).version;
	if (installed !== baseline) {
		console.error(`sync-subagents-kit: ${BRANCH} 分支的基线是 ${baseline},已安装的是 ${installed}——先把 kit 分支 rebase 到已安装版本再同步`);
		return 1;
	}
	const staging = mkdtempSync(join(tmpdir(), "subagents-kit-"));
	const archive = join(staging, "src.tar");
	execFileSync("git", ["-C", KIT, "archive", "-o", archive, BRANCH, "src"]);
	execFileSync("tar", ["-x", "-f", archive, "-C", staging]);
	const incoming = join(staging, "src");
	const live = join(PKG, "src");
	if (existsSync(live) && sameTree(incoming, live)) {
		console.log(`sync-subagents-kit: 已是 ${BRANCH} 分支内容,跳过`);
		rmSync(staging, { recursive: true, force: true });
		return 0;
	}
	const outgoing = join(PKG, "src.replaced");
	rmSync(outgoing, { recursive: true, force: true });
	if (existsSync(live)) renameSync(live, outgoing);
	cpSync(incoming, live, { recursive: true });
	rmSync(outgoing, { recursive: true, force: true });
	rmSync(staging, { recursive: true, force: true });
	rmSync(join(tmpdir(), "jiti"), { recursive: true, force: true });
	console.log(`sync-subagents-kit: 已把 ${BRANCH}(${kitGit("rev-parse", "--short", BRANCH)}) 的 src 同步到 ${PKG},并清理 jiti 编译缓存`);
	return 0;
}

try {
	process.exit(main());
} catch (error) {
	console.error(`sync-subagents-kit: 失败 ${String(error?.message ?? error).slice(0, 400)}`);
	process.exit(1);
}
