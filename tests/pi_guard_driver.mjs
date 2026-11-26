import { spawn, spawnSync } from "node:child_process";
import { constants as osConstants } from "node:os";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const realHome = os.homedir();
const [mode] = process.argv.slice(2);
const spec = mode === "unit" ? {} : JSON.parse(fs.readFileSync(0, "utf8"));
const home = fs.mkdtempSync(path.join(os.tmpdir(), "pi-guard-driver-"));
process.env.HOME = home;
for (const [key, value] of Object.entries(spec.env ?? {})) process.env[key] = value;
const guard = await import("../extensions/pi-guard.ts");

const MB = 1024 * 1024;
const GB = 1024 * MB;
const STEP_MS = 500;
const INCIDENT_LINE = "[apigate] 收到 429：该调用让出并发槽排队等待，并发容量降为 1（30 秒后重试）";
const HOT_LOOP = `cd /srv/app && git status --porcelain; PYTHONDONTWRITEBYTECODE=1 python3 - <<'EOF' 2>&1\nimport sys\nitems = []\nwhile True:\n    items.append("x" * 1000)\n    sys.stderr.write("${INCIDENT_LINE}\\n")\nEOF`;
const SPIN_SECONDS = 9;

function repeated(lines, line = INCIDENT_LINE) {
	return Array.from({ length: lines }, () => line).join("\n");
}

function varied(lines) {
	return Array.from({ length: lines }, (_, index) => `row ${index} name${index} value=${index * 7}`).join("\n");
}

function diverse(lines) {
	const shapes = ["load model shard", "step done ok", "warn: low disk space", "info: index rebuilt", "cache miss ratio measured", "checkpoint written"];
	return Array.from({ length: lines }, (_, index) => shapes[index % shapes.length]).join("\n");
}

function configWith(overrides) {
	const config = guard.mergeConfig(overrides);
	config.sliceMax = overrides.sliceMax ?? 300 * MB;
	return config;
}

function newRun(overrides = {}) {
	return guard.createRunState({ toolCallId: "c1", unit: "", original: "x", spinEligible: true, contained: true, startedAt: 1_000_000, ...overrides });
}

function feed(run, config, ticks, plan) {
	const actions = [];
	let cpu = 0;
	for (let tick = 1; tick <= ticks; tick += 1) {
		const now = run.startedAt + tick * STEP_MS;
		if (plan.text) {
			run.pendingText = typeof plan.text === "function" ? plan.text(tick) : plan.text;
			run.freshUpdates = plan.silentAt?.includes(tick) ? 0 : 1;
		}
		const anon = plan.anonAt ? plan.anonAt(tick) : 100 * MB;
		cpu += (typeof plan.cores === "function" ? plan.cores(tick) : (plan.cores ?? 0)) * STEP_MS * 1000;
		const action = guard.stepRun(run, now, [anon, cpu, tick * (plan.readStep ?? 0), tick * (plan.writeStep ?? 0), plan.oom ?? 0], config);
		if (action !== "none") actions.push({ tick, action });
	}
	return actions;
}

async function unit() {
	const out = {};
	out.shq = ["", "abc", "it's", "a'b'c", '$HOME `x` "y"', "line1\nline2", "中文 '引号'", "\\"].map((value) => {
		const quoted = guard.shq(value);
		const probe = spawnSync("/bin/sh", ["-c", `printf '%s' ${quoted}`], { encoding: "utf8" });
		return { value, quoted, roundTrip: probe.stdout === value };
	});
	const wrapConfig = configWith({});
	const unit = guard.nextUnitName(4242, 7);
	const wrapped = guard.wrapCommand("echo 'it' \"is\" $HOME", unit, wrapConfig);
	out.wrap = {
		unit,
		wrapped,
		marker: guard.isWrapped(wrapped),
		plainMarked: guard.isWrapped("echo --unit=pi-guard-x"),
		smallFits: guard.wrapFits(wrapped),
		hugeFits: guard.wrapFits(guard.wrapCommand("x".repeat(140_000), unit, wrapConfig)),
		quoteHeavyFits: guard.wrapFits(guard.wrapCommand("'".repeat(60_000), unit, wrapConfig)),
		quoteHeavyBytes: Buffer.byteLength(guard.wrapCommand("'".repeat(60_000), unit, wrapConfig)),
	};
	const parityCommand = `echo "shlvl=$SHLVL inv=\${INVOCATION_ID:-none}"; printf '%s' "it's"; pwd; exit 5`;
	const env = { ...process.env, INVOCATION_ID: "abcdef" };
	const { INVOCATION_ID, ...bareEnv } = env;
	const plain = spawnSync("/bin/bash", ["-c", parityCommand], { encoding: "utf8", env: bareEnv, cwd: "/tmp" });
	const offset = spawnSync("/bin/bash", ["-c", `exec /usr/bin/env -u INVOCATION_ID SHLVL=$((SHLVL - 1)) /bin/bash -c ${guard.shq(parityCommand)}`], { encoding: "utf8", env, cwd: "/tmp" });
	out.wrapParity = { sameOutput: plain.stdout === offset.stdout, sameStatus: plain.status === offset.status, plain: plain.stdout, offset: offset.stdout };

	out.inline = [
		[HOT_LOOP, true],
		['python3 -c "print(1)"', true],
		["node -e 'while(1){}'", true],
		["bash -c 'while true; do echo x; done'", true],
		["perl -e 'print 1 while 1'", true],
		["ruby -e 'loop{}'", true],
		["php -r 'while(1){}'", true],
		['awk \'BEGIN{while(1)print "x"}\'', true],
		['/usr/bin/env python3 -c "x"', true],
		["FOO=1 python3 - <<EOF\nprint(1)\nEOF", true],
		["python3 -u - <<'PY'\nprint(1)\nPY", true],
		['time python3 -c "x"', true],
		['cat x | python3 -c "import sys; sys.stdin.read()"', true],
		['python3.12 -c "x"', true],
		['./venv/bin/python -c "x"', true],
		['while true; do python3 -c "print(1)"; done', true],
		['node --eval "1"', true],
		["python3 - <<'EOF' 2>&1\nprint(1)\nEOF", true],
		["bash -lc 'echo hi'", true],
		["python3 script.py 2>&1 <<'EOF'\nprint(1)\nEOF", false],
		["python3 script.py", false],
		["python3 -m pytest -q", false],
		["python3 script.py <<EOF\n1\nEOF", false],
		['cat <<\'EOF\'\npython3 -c "print(1)"\nEOF', false],
		['echo python3 -c "print(1)"', false],
		['echo "python3 -c print(1)"', false],
		['git commit -m "fix python3 -c crash"', false],
		["node server.js", false],
		["python3 -- -c", false],
		["ls -la", false],
		["awk -f prog.awk data.txt", false],
		["./python3.sh -c x", false],
		["PYTHON=python3 python3 script.py", false],
		["npm run build", false],
		["timeout 10 python3 -c 'x'", false],
		["docker run img python3 -c 'x'", false],
	].map(([command, expected]) => ({ command, expected, actual: guard.isInlineScript(command) }));

	out.bounded = [
		["x", 30, true],
		["x", 0, false],
		["timeout 60 python3 -c 'x'", undefined, true],
		["timeout -k 5 30 cmd", undefined, true],
		["cd /x && timeout 1m sleep 9", undefined, true],
		["echo a | timeout 10 python3 x.py", undefined, true],
		["xargs timeout 30 sh -c 'x'", undefined, true],
		["find . -exec timeout 30 x {} \\;", undefined, true],
		["python3 -c 'x'", undefined, false],
		["TIMEOUT=5; python3 x.py", undefined, false],
		["echo timeout 5", undefined, false],
		["curl --max-time 5 x", undefined, false],
		["cat <<'EOF'\ntimeout 5 x\nEOF", undefined, false],
	].map(([command, timeout, expected]) => ({ command, expected, actual: guard.isExplicitlyBounded(command, timeout) }));

	const repeatConfig = configWith({});
	out.dominant = [
		{ text: repeated(300), repetitive: true, fraction: 1 },
		{ text: repeated(25), repetitive: true, fraction: 1 },
		{ text: repeated(19), repetitive: false, fraction: 1 },
		{ text: Array.from({ length: 300 }, (_, index) => `2026-11-26 11:20:${String(index % 60).padStart(2, "0")} req=${index} ${INCIDENT_LINE}`).join("\n"), repetitive: true, fraction: 1 },
		{ text: repeated(18).concat(`\n${INCIDENT_LINE} last`), repetitive: false, fraction: 0 },
		{ text: varied(300), repetitive: true, fraction: 1 },
		{ text: diverse(300), repetitive: false, fraction: 0 },
		{ text: `${varied(5)}\n${repeated(300)}`, repetitive: true, fraction: 0 },
		{ text: Array.from({ length: 300 }, () => `\u001b[31m${INCIDENT_LINE}\u001b[0m`).join("\n"), repetitive: true, fraction: 0 },
		{ text: "", repetitive: false, fraction: 0 },
		{ text: `partial start of line\n${repeated(40)}`, repetitive: true, fraction: 0 },
	].map((sample) => {
		const stats = guard.dominantLineStats(sample.text);
		return { repetitive: guard.isRepetitive(stats, repeatConfig), expected: sample.repetitive, fraction: Number(stats.fraction.toFixed(3)), fractionAtLeast: sample.fraction, nonEmpty: stats.nonEmpty, topLine: stats.topLine.slice(0, 40) };
	});

	const spinConfig = configWith({ rateWindowMs: STEP_MS });
	const rateTicks = spinConfig.rateWindowMs / STEP_MS;
	const windowTicks = (spinConfig.spinWindowSec * 1000) / STEP_MS;
	out.spin = {
		kill: feed(newRun(), spinConfig, 200, { text: repeated(300), writeStep: 100 * 1024, cores: 1 }).map((entry) => entry.tick),
		expectedKillTick: rateTicks + 1 + windowTicks,
		counterLines: feed(newRun(), spinConfig, 200, { text: varied(300), writeStep: 100 * 1024 }).map((entry) => entry.tick)[0] ?? null,
		diverse: feed(newRun(), spinConfig, 200, { text: diverse(300), writeStep: 100 * 1024 }).length,
		readsInput: feed(newRun(), spinConfig, 200, { text: repeated(300), writeStep: 100 * 1024, readStep: 200 * 1024 }).length,
		lowOutput: feed(newRun(), spinConfig, 200, { text: repeated(300), writeStep: 2048 }).length,
		silentTick: feed(newRun(), spinConfig, 200, { text: repeated(300), writeStep: 100 * 1024, silentAt: [20, 40] }).map((entry) => entry.tick),
		staleTick: feed(newRun(), spinConfig, 200, { text: repeated(300), writeStep: 100 * 1024, silentAt: [20, 21, 22] }).map((entry) => entry.tick),
		resumed: feed(newRun(), spinConfig, 300, { text: (tick) => (tick === 80 ? diverse(300) : repeated(300)), writeStep: 100 * 1024 }).map((entry) => entry.tick),
		notEligible: feed(newRun({ spinEligible: false }), spinConfig, 200, { text: repeated(300), writeStep: 100 * 1024 }).length,
		tooFewLines: feed(newRun(), spinConfig, 200, { text: repeated(19), writeStep: 100 * 1024 }).length,
	};
	out.spin.killAt = out.spin.kill[0] ?? null;
	out.spin.resumedAt = out.spin.resumed[0] ?? null;
	out.spin.silentAt = out.spin.silentTick[0] ?? null;
	out.spin.staleAt = out.spin.staleTick[0] ?? null;
	delete out.spin.kill;
	delete out.spin.resumed;
	delete out.spin.silentTick;
	delete out.spin.staleTick;

	const ceilingConfig = configWith({ sliceMax: 300 * MB });
	const growing = (tick) => tick * 100 * MB;
	out.ceiling = {
		observed: feed(newRun({ contained: false }), ceilingConfig, 10, { anonAt: growing }),
		kernelHandles: feed(newRun({ contained: true }), ceilingConfig, 10, { anonAt: growing }).length,
	};

	const suspectConfig = configWith({ rateWindowMs: STEP_MS, spinSuspectSec: 300 });
	const suspects = (plan) => {
		const run = newRun();
		feed(run, suspectConfig, 620, plan);
		return run.spinSuspect;
	};
	out.suspect = {
		singleCoreFlat: suspects({ cores: 1 }),
		halfCore: suspects({ cores: 0.5 }),
		singleCoreRising: suspects({ cores: 1, anonAt: (tick) => 100 * MB + tick * MB }),
		bursty: suspects({ cores: (tick) => (tick % 2 === 0 ? 1 : 0) }),
	};

	const leakConfig = configWith({ rateWindowMs: STEP_MS });
	const leakVerdict = (anonAt, ticks) => {
		const run = newRun();
		feed(run, leakConfig, ticks, { anonAt });
		return { verdict: guard.finalizeRun(run, run.startedAt + ticks * STEP_MS, 0, false, 0, leakConfig), slopeMBps: run.leakSlope === null ? null : Number((run.leakSlope / MB).toFixed(2)) };
	};
	out.leak = {
		rising: leakVerdict((tick) => 100 * MB + tick * MB, 640),
		fastEnoughButShort: leakVerdict((tick) => 100 * MB + tick * MB, 400),
		slow: leakVerdict((tick) => 100 * MB + tick * 0.25 * MB, 640),
		flat: leakVerdict(() => 300 * MB, 640),
		sawtooth: leakVerdict((tick) => (tick % 20) * 5 * MB, 640),
	};

	const oomConfig = configWith({});
	const oomVerdict = (oomNow, failed, exitCode) => {
		const run = newRun();
		feed(run, oomConfig, 12, { anonAt: () => 5 * GB, oom: 5 });
		return guard.finalizeRun(run, run.startedAt + 12 * STEP_MS, oomNow, failed, exitCode, oomConfig);
	};
	out.finalize = {
		oomKilled: oomVerdict(6, true, 137),
		oomFailedOther: oomVerdict(6, true, 1),
		oomExitedZero: oomVerdict(6, false, 0),
		oomLongAgo: (() => {
			const run = newRun();
			feed(run, oomConfig, 12, { anonAt: () => 5 * GB, oom: 5 });
			feed(run, oomConfig, 30, { anonAt: () => 5 * GB, oom: 6 });
			return guard.finalizeRun(run, run.startedAt + 42 * STEP_MS, 6, true, 137, oomConfig);
		})(),
		bigOk: oomVerdict(5, false, 0),
	};
	const killedSpin = newRun();
	killedSpin.killed = "spin";
	killedSpin.spinProofMs = 65_000;
	killedSpin.outRate = 312_000;
	killedSpin.inRate = 400;
	killedSpin.dominant = guard.dominantLineStats(repeated(300));
	out.finalize.spinWins = guard.finalizeRun(killedSpin, 0, 9, true, 137, oomConfig);
	const killedCeiling = newRun({ contained: false });
	killedCeiling.killed = "ceiling";
	killedCeiling.peakAnon = 300 * MB;
	out.finalize.ceiling = guard.finalizeRun(killedCeiling, 0, 0, true, 137, oomConfig);
	out.annotation = {
		spin: guard.annotationFor(killedSpin, oomConfig, 65_000, false),
		accumulate: guard.annotationFor(killedCeiling, oomConfig, 9000, false),
		wrapFailed: guard.annotationFor(newRun(), oomConfig, 5, true),
		quiet: guard.annotationFor(newRun(), oomConfig, 1200, false),
		longNormal: guard.annotationFor({ ...newRun(), sampled: true }, oomConfig, 45_000, false),
		untracked: guard.annotationFor(newRun(), oomConfig, 45_000, false),
	};
	out.fold = {
		repetitive: guard.foldRepetitive(`${repeated(300)}\n\nCommand exited with code 137`, oomConfig),
		diverse: guard.foldRepetitive(`${diverse(300)}\n\nCommand exited with code 137`, oomConfig),
	};
	out.config = {
		merged: (() => {
			const merged = guard.mergeConfig({ enabled: "no", reserveFrac: 0.5, sliceMaxBytes: 123, slice: "bad name", spinWindowSec: -3, tickMs: 1, repeatFrac: 3, maxInBytesPerSec: Number.NaN });
			return { enabled: merged.enabled, reserveFrac: merged.reserveFrac, sliceMaxBytes: merged.sliceMaxBytes, slice: merged.slice, spinWindowSec: merged.spinWindowSec, tickMs: merged.tickMs, repeatFrac: merged.repeatFrac, maxInBytesPerSec: merged.maxInBytesPerSec };
		})(),
		maxFromTotal: guard.sliceMaxBytesFor(16 * GB, guard.mergeConfig({})),
		maxOverride: guard.sliceMaxBytesFor(16 * GB, guard.mergeConfig({ sliceMaxBytes: 1000, reserveFrac: 0.9 })),
		missing: guard.loadConfig(path.join(home, "nope.json")).spinWindowSec,
		malformed: (() => {
			const file = path.join(home, "bad.json");
			fs.writeFileSync(file, "{not json");
			return guard.loadConfig(file).enabled;
		})(),
		valid: (() => {
			const file = path.join(home, "ok.json");
			fs.writeFileSync(file, JSON.stringify({ enabled: false, reserveFrac: 0.5 }));
			const loaded = guard.loadConfig(file);
			return { enabled: loaded.enabled, sliceMax: loaded.sliceMax, expected: Math.floor(os.totalmem() * 0.5) };
		})(),
	};
	const logFile = path.join(home, "log.jsonl");
	fs.writeFileSync(logFile, Array.from({ length: 12 }, (_, index) => JSON.stringify({ ts: `2026-11-26T11:00:${String(index).padStart(2, "0")}.000Z`, verdict: "normal", action: "none", durationMs: index, peakAnonMB: index, cmd: `cmd ${index}` })).join("\n"));
	out.recentLog = guard.recentLogLines(logFile, 10);
	const rows = [
		{ pid: 10, ppid: 1, pgrp: 10, session: 10, start: 100, cpuUs: 10 },
		{ pid: 20, ppid: 10, pgrp: 20, session: 20, start: 200, cpuUs: 20 },
		{ pid: 30, ppid: 20, pgrp: 20, session: 20, start: 300, cpuUs: 30 },
		{ pid: 40, ppid: 20, pgrp: 40, session: 40, start: 400, cpuUs: 40 },
		{ pid: 50, ppid: 1, pgrp: 50, session: 50, start: 500, cpuUs: 50 },
		{ pid: 60, ppid: 10, pgrp: 60, session: 60, start: 250, cpuUs: 60 },
	];
	out.processes = {
		tree: guard.processTree(20, rows).map((row) => row.pid).sort((a, b) => a - b),
		missing: guard.processTree(99, rows).map((row) => row.pid),
		leader: [[10, 1], [20, 10], [30, 20], [40, 20], [60, 10]].map(([pid, parent]) => guard.isSessionLeaderChild(rows.find((row) => row.pid === pid), parent)),
		startedAt: guard.startedAtMs(rows[0], 5000),
		fresh: guard.freshSessionLeaders(rows, 10, 1_002_500, 1_000_000, new Set()).map((row) => row.pid),
		knownExcluded: guard.freshSessionLeaders(rows, 10, 1_002_500, 1_000_000, new Set([60])).map((row) => row.pid),
		tooOld: guard.freshSessionLeaders(rows, 10, 1_010_000, 1_000_000, new Set()).map((row) => row.pid),
		statusFields: [guard.flatValue("RssAnon:\t  31896 kB\nVmRSS: 1 kB", "RssAnon:"), guard.flatValue("rchar: 79479\nwchar: 5\n", "wchar:"), guard.flatValue("oom_kill 3\noom_group_kill 1\n", "oom_kill"), guard.flatValue("anon 4096\nfile 1\n", "anon")],
	};
	const longRun = newRun();
	const longActions = feed(longRun, spinConfig, 6000, { text: diverse(300), writeStep: 100 * 1024, cores: 4 }).length;
	const coreRun = newRun();
	const coreActions = feed(coreRun, suspectConfig, 2000, { cores: 1 }).length;
	out.signature = {
		longDiverse: longActions,
		longVerdict: guard.finalizeRun(longRun, longRun.startedAt + 6000 * STEP_MS, 0, false, 0, spinConfig),
		longSilent: feed(newRun(), spinConfig, 6000, { cores: 1 }).length,
		bigFlatContained: feed(newRun(), spinConfig, 600, { anonAt: () => 11 * GB, cores: 4 }).length,
		singleCore: coreActions,
		singleCoreFlagged: coreRun.spinSuspect,
		singleCoreVerdict: guard.finalizeRun(coreRun, coreRun.startedAt + 2000 * STEP_MS, 0, false, 0, suspectConfig),
	};
	const brief = newRun();
	guard.finalizeRun(brief, brief.startedAt, 0, false, 0, oomConfig);
	out.shouldLog = [guard.shouldLog(brief, 500, "contained"), guard.shouldLog(brief, 500, "observed"), guard.shouldLog(brief, 3000, "contained"), guard.shouldLog(killedSpin, 500, "contained")];
	return out;
}

function fakeExec(handlers, ctx, id, command, input) {
	return new Promise((resolve) => {
		let tail = "";
		let timer = null;
		let last = 0;
		const emit = () => {
			last = Date.now();
			handlers.tool_execution_update?.({ type: "tool_execution_update", toolName: "bash", toolCallId: id, args: { command }, partialResult: { content: [{ type: "text", text: tail }] } }, ctx);
		};
		const onData = (chunk) => {
			tail = (tail + chunk.toString("utf8")).slice(-50 * 1024);
			const delay = 100 - (Date.now() - last);
			if (delay <= 0) {
				if (timer) clearTimeout(timer);
				timer = null;
				emit();
				return;
			}
			if (timer === null) {
				timer = setTimeout(() => {
					timer = null;
					emit();
				}, delay);
			}
		};
		const child = spawn("/bin/bash", ["-c", input.command], { cwd: process.cwd(), detached: true, stdio: ["ignore", "pipe", "pipe"] });
		child.stdout.on("data", onData);
		child.stderr.on("data", onData);
		child.on("error", (error) => resolve({ content: [{ type: "text", text: String(error.message) }], isError: true }));
		child.on("exit", (code, signal) => {
			if (timer) clearTimeout(timer);
			emit();
			const exitCode = code ?? (signal ? 128 + osConstants.signals[signal] : 1);
			const structuredContent = { output: tail, truncated: false, exit_code: exitCode, wall_time_seconds: 0 };
			resolve(exitCode === 0
				? { content: [{ type: "text", text: tail || "(no output)" }], structuredContent }
				: { content: [{ type: "text", text: `${tail ? `${tail}\n\n` : ""}Command exited with code ${exitCode}` }], isError: true, structuredContent });
		});
	});
}

async function runCall(handlers, ctx, tool, call) {
	const input = { command: call.command };
	if (call.timeout !== undefined) input.timeout = call.timeout;
	const original = call.command;
	const toolName = call.toolName ?? "bash";
	await handlers.tool_execution_start?.({ type: "tool_execution_start", toolName, toolCallId: call.id, args: { command: original } }, ctx);
	await handlers.tool_call?.({ type: "tool_call", toolName, toolCallId: call.id, input }, ctx);
	const started = Date.now();
	const onUpdate = (partialResult) => handlers.tool_execution_update?.({ type: "tool_execution_update", toolName: "bash", toolCallId: call.id, args: { command: original }, partialResult }, ctx);
	let result;
	try {
		result = tool ? await tool.execute(call.id, input, undefined, onUpdate, undefined) : await fakeExec(handlers, ctx, call.id, original, input);
	} catch (error) {
		result = { content: [{ type: "text", text: String(error?.message ?? error) }], isError: true };
	}
	const event = { type: "tool_result", toolName: "bash", toolCallId: call.id, input, content: result.content, details: result.details, isError: result.isError === true };
	if (result.structuredContent !== undefined) event.structuredContent = result.structuredContent;
	const hook = await handlers.tool_result?.(event, ctx);
	const content = hook?.content ?? result.content;
	const isError = hook?.isError ?? event.isError;
	const durationMs = Date.now() - started;
	await handlers.tool_execution_end?.({ type: "tool_execution_end", toolName: "bash", toolCallId: call.id, result: { ...result, content }, isError, durationMs }, ctx);
	return {
		id: call.id,
		rewritten: input.command !== original,
		isError,
		exitCode: result.structuredContent?.exit_code ?? null,
		hookStructured: hook?.structuredContent === undefined ? null : JSON.stringify(hook.structuredContent) === JSON.stringify(result.structuredContent),
		content: content.filter((part) => part.type === "text").map((part) => part.text),
		durationMs,
	};
}

async function runSpec() {
	const configPath = path.join(home, "pi-guard.json");
	fs.writeFileSync(configPath, JSON.stringify(spec.config ?? {}));
	process.env.PI_GUARD_CONFIG = configPath;
	const handlers = {};
	const commands = [];
	const notes = [];
	const ctx = { hasUI: true, isIdle: () => true, cwd: process.cwd(), ui: { notify: (message, type) => notes.push({ message, type }) } };
	await guard.default({
		on: (event, handler) => {
			handlers[event] = handler;
		},
		registerCommand: (name, options) => commands.push({ name, options }),
	});
	await new Promise((resolve) => setTimeout(resolve, spec.settleMs ?? 500));
	let tool = null;
	if (spec.tool === "pi") {
		tool = (await import(path.join(realHome, ".local/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/tools/bash.js"))).createBashTool(process.cwd());
	}
	const results = [];
	const sliceOf = () => /slice (\/\S+)/.exec(notes.filter((note) => note.type === "info").map((note) => note.message)[0] ?? "")?.[1] ?? null;
	const limitOf = (sliceDir, name) => (sliceDir === null || !fs.existsSync(path.join(sliceDir, name)) ? null : fs.readFileSync(path.join(sliceDir, name), "utf8").trim());
	let limitsDuringLastCall = null;
	for (const [index, item] of spec.calls.entries()) {
		const started = (Array.isArray(item) ? item : [item]).map((call) => runCall(handlers, ctx, tool, call));
		if (spec.limitsDuringLastCall && index === spec.calls.length - 1) {
			await new Promise((resolve) => setTimeout(resolve, 700));
			await commands[0].options.handler("", ctx);
			const sliceDir = sliceOf();
			limitsDuringLastCall = { memoryMax: limitOf(sliceDir, "memory.max"), memorySwapMax: limitOf(sliceDir, "memory.swap.max") };
		}
		results.push(...(await Promise.all(started)));
	}
	await new Promise((resolve) => setTimeout(resolve, 200));
	await commands[0].options.handler("", ctx);
	const status = notes.filter((note) => note.type === "info").map((note) => note.message)[0] ?? null;
	const sliceDir = status === null ? null : /slice (\/\S+)/.exec(status)?.[1] ?? null;
	const logFile = path.join(home, ".pi", "agent", "pi-guard", "log.jsonl");
	for (const name of [].concat(spec.stopSlice ?? [])) spawnSync("systemctl", ["--user", "stop", name], { encoding: "utf8" });
	return {
		results,
		notes,
		status,
		sliceDir,
		limitsDuringLastCall,
		log: fs.existsSync(logFile) ? fs.readFileSync(logFile, "utf8").split("\n").filter(Boolean).map((line) => JSON.parse(line)) : [],
	};
}

const output = mode === "unit" ? await unit() : await runSpec();
process.stdout.write(`${JSON.stringify(output)}\n`);
