import { formatJobs, listJobs, storePath } from "../extensions/subagent-jobs.ts";

const [scenario, payload] = process.argv.slice(2);
const p = JSON.parse(payload || "{}");
const out = {};

if (scenario === "format") {
	out.text = formatJobs(p.jobs ?? []);
} else if (scenario === "list") {
	out.outcome = await listJobs(p.cwd, p.noSessionId ? undefined : p.sessionId ?? "sess-1");
} else if (scenario === "path") {
	out.path = storePath(p.cwd ?? "/w", p.sessionId ?? "s");
}

console.log(JSON.stringify(out));
