import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync } from "node:fs";
import { homedir, totalmem } from "node:os";
import { basename, dirname, join } from "node:path";
import type { ExtensionAPI, ToolResultEventResult } from "@earendil-works/pi-coding-agent";

const MAX_ARGV_BYTES = 131000;
const TASKS_MAX = 4096;
const CGROUP_ROOT = process.env.PI_GUARD_CGROUP_ROOT ?? "/sys/fs/cgroup";
const PROC_ROOT = "/proc";
const ENV_BIN = "/usr/bin/env";
const CLOCK_TICK_US = 10000;
const START_SLACK_MS = 2000;
const SCOPE_WAIT_MS = 3000;
const SCOPE_POLL_MS = 10;
const REPROBE_MS = 60000;
const PROBE_TIMEOUT_MS = 8000;
const WRAP_FAILURE_WINDOW_MS = 1000;
const OOM_RECENT_MS = 3000;
const ENVELOPE_STEP_MS = 5000;
const ENVELOPE_TOLERANCE_BYTES = 32 * 1024 * 1024;
const FLAT_BYTES = 64 * 1024 * 1024;
const FLAT_FRACTION = 0.1;
const CORES_BAND = 0.15;
const TIMELINE_FIELDS = 6;
const TIMELINE_SAMPLES = 32;
const ENVELOPE_SAMPLES = 64;
const LOG_ROTATE_BYTES = 1024 * 1024;
const LOG_SHOW_LINES = 10;
const LOG_MIN_DURATION_MS = 2000;
const CMD_LOG_CHARS = 120;
const SIGKILL_EXIT = 137;
const AT = 0;
const ANON = 1;
const CPU = 2;
const READ = 3;
const WRITTEN = 4;
const OOM = 5;
const SAMPLE_ANON = 0;
const SAMPLE_CPU = 1;
const SAMPLE_READ = 2;
const SAMPLE_WRITTEN = 3;
const SAMPLE_OOM = 4;
const MIN_TICK_MS = 50;
const MAX_TICK_MS = 5000;
const MIN_RATE_WINDOW_MS = 500;
const WRAP_HEAD = /^exec '[^'\n]+' --user --scope --quiet --collect --unit=pi-guard-/;
const WRAP_FAILURE = /^Failed to (?:connect to bus|start|create|launch|set|activate|lookup|add)[^\n]*\n+Command exited with code 1$/;
const EMPTY_SAMPLE: readonly number[] = [0, 0, 0, 0, 0];

export type GuardConfig = {
	enabled: boolean;
	reserveFrac: number;
	sliceMaxBytes: number | null;
	slice: string;
	systemdRun: string;
	bash: string;
	spinWindowSec: number;
	minOutBytesPerSec: number;
	maxInBytesPerSec: number;
	repeatFrac: number;
	minRepeatLines: number;
	bigAnonBytes: number;
	leakBytesPerSec: number;
	leakWindowSec: number;
	spinSuspectSec: number;
	reportMinSec: number;
	rateWindowMs: number;
	tickMs: number;
	sliceMax: number;
};

export const DEFAULT_CONFIG: GuardConfig = {
	enabled: true,
	reserveFrac: 0.25,
	sliceMaxBytes: null,
	slice: "piguard.slice",
	systemdRun: "/usr/bin/systemd-run",
	bash: "/bin/bash",
	spinWindowSec: 60,
	minOutBytesPerSec: 102400,
	maxInBytesPerSec: 20480,
	repeatFrac: 0.9,
	minRepeatLines: 20,
	bigAnonBytes: 2 * 1024 * 1024 * 1024,
	leakBytesPerSec: 1024 * 1024,
	leakWindowSec: 300,
	spinSuspectSec: 300,
	reportMinSec: 30,
	rateWindowMs: 5000,
	tickMs: 500,
	sliceMax: 0,
};

const CONFIG_KEYS = Object.keys(DEFAULT_CONFIG) as (keyof GuardConfig)[];
const SLICE_NAME = /^[A-Za-z0-9:_\\-]+\.slice$/;

export function mergeConfig(raw: unknown): GuardConfig {
	const config: GuardConfig = { ...DEFAULT_CONFIG };
	if (!raw || typeof raw !== "object") return config;
	const source = raw as Record<string, unknown>;
	for (const key of CONFIG_KEYS) {
		const value = source[key];
		const fallback = DEFAULT_CONFIG[key];
		if (fallback === null) continue;
		if (typeof fallback === "boolean" ? typeof value === "boolean" : typeof fallback === "string" ? typeof value === "string" && value !== "" : typeof value === "number" && Number.isFinite(value)) {
			Object.assign(config, { [key]: value });
		}
	}
	if (typeof source.sliceMaxBytes === "number" && Number.isFinite(source.sliceMaxBytes) && source.sliceMaxBytes > 0) {
		config.sliceMaxBytes = Math.floor(source.sliceMaxBytes);
	}
	if (!SLICE_NAME.test(config.slice)) config.slice = DEFAULT_CONFIG.slice;
	config.reserveFrac = clamp(config.reserveFrac, 0, 0.95);
	config.repeatFrac = clamp(config.repeatFrac, 0.5, 1);
	config.tickMs = clamp(config.tickMs, MIN_TICK_MS, MAX_TICK_MS);
	config.rateWindowMs = clamp(config.rateWindowMs, MIN_RATE_WINDOW_MS, (TIMELINE_SAMPLES * config.tickMs) / 2);
	config.leakWindowSec = Math.min(config.leakWindowSec, (ENVELOPE_SAMPLES * ENVELOPE_STEP_MS) / 1000);
	config.spinWindowSec = Math.max(config.spinWindowSec, 1);
	config.minRepeatLines = Math.max(config.minRepeatLines, 1);
	config.reportMinSec = Math.max(config.reportMinSec, 0);
	return config;
}

function clamp(value: number, low: number, high: number): number {
	return Math.min(high, Math.max(low, value));
}

export function sliceMaxBytesFor(totalBytes: number, config: GuardConfig): number {
	if (config.sliceMaxBytes !== null) return config.sliceMaxBytes;
	return Math.floor(totalBytes * (1 - config.reserveFrac));
}

export function shq(text: string): string {
	return `'${text.replaceAll("'", `'\\''`)}'`;
}

export function wrapCommand(command: string, unit: string, config: GuardConfig): string {
	return [
		"exec",
		shq(config.systemdRun),
		"--user --scope --quiet --collect",
		`--unit=${unit}`,
		`--slice=${config.slice}`,
		"-p MemorySwapMax=0",
		`-p TasksMax=${TASKS_MAX}`,
		"--",
		shq(ENV_BIN),
		"-u INVOCATION_ID",
		"SHLVL=$((SHLVL - 1))",
		shq(config.bash),
		"-c",
		shq(command),
	].join(" ");
}

export function isWrapped(command: string): boolean {
	return WRAP_HEAD.test(command);
}

export function wrapFits(wrapped: string): boolean {
	return Buffer.byteLength(wrapped, "utf8") <= MAX_ARGV_BYTES;
}

export function nextUnitName(pid: number, instance: string, seq: number): string {
	return `pi-guard-${pid}-${instance}-${seq}`;
}

export type ShellToken = { text: string; quoted: boolean; redirect: boolean };

const COMMAND_SEPARATORS = new Set([";", "&", "|", "\n", "(", ")", "`"]);
const RESERVED_WORDS = new Set(["!", "{", "if", "then", "do", "else", "elif", "while", "until", "coproc"]);
const WRAPPER_WORDS = new Set([
	"command", "exec", "env", "sudo", "doas", "nice", "nohup", "setsid", "stdbuf", "ionice", "taskset", "chrt", "time",
	"strace", "ltrace", "valgrind", "run", "xargs", "mpiexec", "mpirun",
]);
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
const DIGITS_ONLY = /^\d+$/;

export function shellCommands(source: string): ShellToken[][] {
	const commands: ShellToken[][] = [];
	let tokens: ShellToken[] = [];
	let text = "";
	let marked = false;
	let redirectNext = false;
	let quote = "";
	let heredoc: string | null = null;
	const flush = (adjacentRedirect: boolean): void => {
		if (text === "" && !marked) return;
		tokens.push({ text, quoted: marked, redirect: redirectNext || (adjacentRedirect && DIGITS_ONLY.test(text)) });
		text = "";
		marked = false;
		redirectNext = false;
	};
	for (let i = 0; i < source.length; i += 1) {
		const ch = source[i];
		if (quote !== "") {
			if (ch === "\\" && i + 1 < source.length) {
				if (source[i + 1] === "\n") continue;
				if (quote === '"' && "\"\\$`".includes(source[i + 1])) {
					text += source[i + 1];
					i += 1;
					continue;
				}
				text += ch;
				continue;
			}
			if (ch === quote) {
				quote = "";
				continue;
			}
			text += ch;
			continue;
		}
		if (ch === "\\") {
			if (i + 1 >= source.length) {
				text += ch;
				continue;
			}
			if (source[i + 1] === "\n") {
				i += 1;
				continue;
			}
			text += source[i + 1];
			i += 1;
			continue;
		}
		if (ch === "'" || ch === "\"") {
			flush(false);
			quote = ch;
			marked = true;
			continue;
		}
		if (ch === "<" && source[i + 1] === "<") {
			flush(true);
			heredoc = heredocDelimiter(source, i);
			tokens.push({ text: "<<", quoted: false, redirect: false });
			i += source[i + 2] === "<" || source[i + 2] === "-" ? 2 : 1;
			redirectNext = true;
			continue;
		}
		if (ch === "<" || ch === ">") {
			flush(true);
			if (source[i + 1] === "&") i += 1;
			redirectNext = true;
			continue;
		}
		if (ch === " " || ch === "\t" || ch === "\r") {
			flush(false);
			continue;
		}
		if (COMMAND_SEPARATORS.has(ch)) {
			flush(false);
			if (tokens.length > 0) commands.push(tokens);
			tokens = [];
			redirectNext = false;
			if (ch === "\n" && heredoc !== null) {
				i = heredocEnd(source, i, heredoc);
				heredoc = null;
			}
			continue;
		}
		text += ch;
	}
	flush(false);
	if (tokens.length > 0) commands.push(tokens);
	return commands;
}

function heredocDelimiter(source: string, at: number): string | null {
	let i = at + 2;
	if (source[i] === "<") return null;
	if (source[i] === "-") i += 1;
	const word = source.slice(i).split("\n", 1)[0].trim().split(/\s+/, 1)[0] ?? "";
	return word.replace(/^(['"])(.*)\1$/, "$2") || null;
}

function heredocEnd(source: string, newline: number, delimiter: string): number {
	let at = newline;
	for (;;) {
		const end = source.indexOf("\n", at + 1);
		const line = source.slice(at + 1, end === -1 ? source.length : end).replace(/^\t+/, "");
		if (line === delimiter) return end === -1 ? source.length : end;
		if (end === -1) return source.length;
		at = end;
	}
}

export function commandIndex(tokens: ShellToken[]): number {
	let index = 0;
	while (index < tokens.length) {
		const token = tokens[index];
		if (token.redirect) {
			index += 1;
			continue;
		}
		if (token.quoted) break;
		if (RESERVED_WORDS.has(token.text) || ASSIGNMENT.test(token.text)) {
			index += 1;
			continue;
		}
		if (WRAPPER_WORDS.has(basename(token.text))) {
			index += 1;
			while (index < tokens.length) {
				const option = tokens[index];
				if (option.quoted || !(option.redirect || option.text.startsWith("-") || ASSIGNMENT.test(option.text))) break;
				index += 1;
			}
			continue;
		}
		break;
	}
	return index;
}

type InterpreterSpec = { flags: string[]; exact: string[]; stdinProgram: boolean; programArgument: boolean };

const SHELL_SPEC: InterpreterSpec = { flags: ["c"], exact: [], stdinProgram: true, programArgument: false };
const INTERPRETERS: Record<string, InterpreterSpec> = {
	awk: { flags: [], exact: [], stdinProgram: false, programArgument: true },
	bash: SHELL_SPEC,
	dash: SHELL_SPEC,
	gawk: { flags: [], exact: [], stdinProgram: false, programArgument: true },
	ksh: SHELL_SPEC,
	lua: { flags: ["e"], exact: [], stdinProgram: true, programArgument: false },
	mawk: { flags: [], exact: [], stdinProgram: false, programArgument: true },
	node: { flags: ["e", "p"], exact: ["--eval", "--print"], stdinProgram: true, programArgument: false },
	perl: { flags: ["e", "E"], exact: [], stdinProgram: true, programArgument: false },
	php: { flags: ["r"], exact: [], stdinProgram: true, programArgument: false },
	python: { flags: ["c"], exact: [], stdinProgram: true, programArgument: false },
	ruby: { flags: ["e"], exact: [], stdinProgram: true, programArgument: false },
	sh: SHELL_SPEC,
	zsh: SHELL_SPEC,
};

function interpreterSpec(word: string): InterpreterSpec | null {
	const name = basename(word);
	if (/^python[0-9.]*$/.test(name)) return INTERPRETERS.python ?? null;
	return INTERPRETERS[name] ?? null;
}

function matchesFlag(text: string, spec: InterpreterSpec): boolean {
	if (text.startsWith("--")) return spec.exact.includes(text);
	return [...text.slice(1)].some((letter) => spec.flags.includes(letter));
}

export function runsInlineCode(tokens: ShellToken[]): boolean {
	const index = commandIndex(tokens);
	const head = tokens[index];
	if (!head || head.quoted) return false;
	const spec = interpreterSpec(head.text);
	if (!spec) return false;
	const args = tokens.slice(index + 1).filter((arg) => !arg.redirect);
	if (spec.programArgument) {
		const first = args[0];
		return first !== undefined && (first.quoted || !first.text.startsWith("-"));
	}
	let heredoc = false;
	let positional = false;
	for (const arg of args) {
		if (!arg.quoted && arg.text === "<<") {
			heredoc = true;
			continue;
		}
		if (!arg.quoted && (arg.text === "--" || arg.text === "-")) {
			if (arg.text === "--") break;
			continue;
		}
		if (!arg.quoted && arg.text.startsWith("-")) {
			if (matchesFlag(arg.text, spec)) return true;
			continue;
		}
		positional = true;
	}
	return heredoc && spec.stdinProgram && !positional;
}

export function isWrapFailure(text: string, isError: boolean, durationMs: number, scopeSeen: boolean): boolean {
	return !scopeSeen && isError && durationMs < WRAP_FAILURE_WINDOW_MS && WRAP_FAILURE.test(text.trimEnd());
}

export function isInlineScript(source: string): boolean {
	return shellCommands(source).some(runsInlineCode);
}

const DURATION_SHAPE = /^\.?\d/;
const TIMEOUT_CALLERS = new Set(["xargs", "-exec", "parallel", "watch", "sudo"]);

const TIMEOUT_WORDS = new Set(["timeout", "gtimeout"]);

function hasTimeoutHead(tokens: ShellToken[]): boolean {
	const head = tokens[commandIndex(tokens)];
	if (head !== undefined && !head.quoted && TIMEOUT_WORDS.has(basename(head.text))) return true;
	for (let index = 1; index + 1 < tokens.length; index += 1) {
		const caller = tokens[index - 1];
		const word = tokens[index];
		const duration = tokens[index + 1];
		if (!caller.quoted && TIMEOUT_CALLERS.has(caller.text) && !word.quoted && TIMEOUT_WORDS.has(basename(word.text)) && !duration.quoted && DURATION_SHAPE.test(duration.text)) return true;
	}
	return false;
}

function inlineIsBounded(tokens: ShellToken[]): boolean {
	const index = commandIndex(tokens);
	if (!runsInlineCode(tokens)) return true;
	return tokens.slice(0, index).some((token) => !token.quoted && TIMEOUT_WORDS.has(basename(token.text)));
}

export function isExplicitlyBounded(source: string, timeout?: unknown): boolean {
	if (typeof timeout === "number" && Number.isFinite(timeout) && timeout > 0) return true;
	const segments = shellCommands(source);
	if (!segments.some(hasTimeoutHead)) return false;
	return segments.every(inlineIsBounded);
}

const ANSI_SEQUENCE = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;
const HEX_RUN = /\b[0-9a-f]{8,}\b/g;
const DIGIT_RUN = /\d+/g;
const SHAPE_CAP = 256;
const SAMPLE_CHARS = 160;

export type DominantStats = { nonEmpty: number; topCount: number; topLine: string; fraction: number };

export function lineShape(line: string): string {
	return line.replace(ANSI_SEQUENCE, "").replace(HEX_RUN, "x").replace(DIGIT_RUN, "#");
}

export function dominantLineStats(text: string): DominantStats {
	const counts = new Map<string, number>();
	const samples = new Map<string, string>();
	let nonEmpty = 0;
	let topShape = "";
	let topCount = 0;
	for (const raw of text.split("\n")) {
		const line = raw.trim();
		if (line === "") continue;
		nonEmpty += 1;
		const shape = lineShape(line);
		const count = (counts.get(shape) ?? 0) + 1;
		counts.set(shape, count);
		if (count === 1 && counts.size <= SHAPE_CAP) samples.set(shape, line.slice(0, SAMPLE_CHARS));
		if (count > topCount) {
			topCount = count;
			topShape = shape;
		}
	}
	return { nonEmpty, topCount, topLine: samples.get(topShape) ?? "", fraction: nonEmpty === 0 ? 0 : topCount / nonEmpty };
}

export function isRepetitive(stats: DominantStats, config: GuardConfig): boolean {
	return stats.fraction >= config.repeatFrac && stats.nonEmpty >= config.minRepeatLines;
}

export function flatValue(text: string, key: string): number {
	const at = text.startsWith(key) ? 0 : text.indexOf(`\n${key}`);
	if (at < 0) return 0;
	let start = at + key.length + 1;
	while (start < text.length && (text[start] === " " || text[start] === "\t")) start += 1;
	let end = start;
	while (end < text.length && text.charCodeAt(end) >= 48 && text.charCodeAt(end) <= 57) end += 1;
	return Number(text.slice(start, end));
}

export class Timeline {
	private readonly cells = new Float64Array(TIMELINE_SAMPLES * TIMELINE_FIELDS);
	private head = 0;
	private filled = 0;

	get length(): number {
		return this.filled;
	}

	push(at: number, anon: number, cpu: number, read: number, written: number, oom: number): void {
		const slot = (this.head + this.filled) % TIMELINE_SAMPLES;
		const base = slot * TIMELINE_FIELDS;
		this.cells[base + AT] = at;
		this.cells[base + ANON] = anon;
		this.cells[base + CPU] = cpu;
		this.cells[base + READ] = read;
		this.cells[base + WRITTEN] = written;
		this.cells[base + OOM] = oom;
		if (this.filled === TIMELINE_SAMPLES) this.head = (this.head + 1) % TIMELINE_SAMPLES;
		else this.filled += 1;
	}

	value(index: number, field: number): number {
		return this.cells[((this.head + index) % TIMELINE_SAMPLES) * TIMELINE_FIELDS + field];
	}

	indexAtOrBefore(at: number): number {
		for (let index = this.filled - 1; index >= 0; index -= 1) {
			if (this.value(index, AT) <= at) return index;
		}
		return -1;
	}
}

export type KillKind = "spin" | "ceiling";
export type Verdict = "normal" | "spin" | "accumulate" | "spin-suspect" | "leak-suspect" | "legit-big";
export type StepAction = "none" | "kill-spin" | "kill-ceiling";

export type RunState = {
	toolCallId: string;
	unit: string;
	original: string;
	spinEligible: boolean;
	contained: boolean;
	startedAt: number;
	pendingText: string | null;
	freshUpdates: number;
	timeline: Timeline;
	envelopeAt: Float64Array;
	envelopeMin: Float64Array;
	envelopeMax: Float64Array;
	envelopeHead: number;
	envelopeCount: number;
	envelopeNextAt: number;
	windowMin: number;
	windowMax: number;
	peakAnon: number;
	dominant: DominantStats | null;
	outRate: number;
	inRate: number;
	spinSince: number;
	spinProofMs: number;
	repetitiveAt: number;
	oomBase: number;
	suspectSince: number;
	suspectAt: number;
	spinSuspect: boolean;
	killed: KillKind | null;
	verdict: Verdict | null;
	leakSlope: number | null;
	avgCores: number;
	lastAnon: number;
	lastCpu: number;
	sampled: boolean;
	done: boolean;
	scopeSeen: boolean;
	shellPid: number;
};

export function createRunState(options: { toolCallId: string; unit: string; original: string; spinEligible: boolean; contained: boolean; startedAt: number }): RunState {
	return {
		toolCallId: options.toolCallId,
		unit: options.unit,
		original: options.original,
		spinEligible: options.spinEligible,
		contained: options.contained,
		startedAt: options.startedAt,
		pendingText: null,
		freshUpdates: 0,
		timeline: new Timeline(),
		envelopeAt: new Float64Array(ENVELOPE_SAMPLES),
		envelopeMin: new Float64Array(ENVELOPE_SAMPLES),
		envelopeMax: new Float64Array(ENVELOPE_SAMPLES),
		envelopeHead: 0,
		envelopeCount: 0,
		envelopeNextAt: options.startedAt + ENVELOPE_STEP_MS,
		windowMin: Number.POSITIVE_INFINITY,
		windowMax: Number.NEGATIVE_INFINITY,
		peakAnon: 0,
		dominant: null,
		outRate: 0,
		inRate: 0,
		spinSince: 0,
		spinProofMs: 0,
		repetitiveAt: 0,
		oomBase: 0,
		suspectSince: 0,
		suspectAt: 0,
		spinSuspect: false,
		killed: null,
		verdict: null,
		leakSlope: null,
		avgCores: 0,
		lastAnon: 0,
		lastCpu: 0,
		sampled: false,
		done: false,
		scopeSeen: false,
		shellPid: 0,
	};
}

export function stepRun(run: RunState, now: number, sample: readonly number[], config: GuardConfig): StepAction {
	if (run.killed !== null) return "none";
	run.timeline.push(now, sample[SAMPLE_ANON], sample[SAMPLE_CPU], sample[SAMPLE_READ], sample[SAMPLE_WRITTEN], sample[SAMPLE_OOM]);
	run.sampled = true;
	run.lastAnon = sample[SAMPLE_ANON];
	run.lastCpu = sample[SAMPLE_CPU];
	if (sample[SAMPLE_ANON] > run.peakAnon) run.peakAnon = sample[SAMPLE_ANON];
	if (sample[SAMPLE_ANON] < run.windowMin) run.windowMin = sample[SAMPLE_ANON];
	if (sample[SAMPLE_ANON] > run.windowMax) run.windowMax = sample[SAMPLE_ANON];
	while (now >= run.envelopeNextAt) {
		if (run.windowMin <= run.windowMax) pushEnvelope(run, run.envelopeNextAt - ENVELOPE_STEP_MS, run.windowMin, run.windowMax);
		run.windowMin = sample[SAMPLE_ANON];
		run.windowMax = sample[SAMPLE_ANON];
		run.envelopeNextAt += ENVELOPE_STEP_MS;
	}
	if (!run.contained && config.sliceMax > 0 && sample[SAMPLE_ANON] >= config.sliceMax) {
		run.killed = "ceiling";
		return "kill-ceiling";
	}
	if (run.spinEligible && spinStep(run, now, sample, config)) {
		run.killed = "spin";
		run.spinProofMs = now - run.spinSince;
		return "kill-spin";
	}
	suspectStep(run, now, sample, config);
	return "none";
}

function pushEnvelope(run: RunState, at: number, min: number, max: number): void {
	run.envelopeAt[run.envelopeHead] = at;
	run.envelopeMin[run.envelopeHead] = min;
	run.envelopeMax[run.envelopeHead] = max;
	run.envelopeHead = (run.envelopeHead + 1) % ENVELOPE_SAMPLES;
	run.envelopeCount = Math.min(run.envelopeCount + 1, ENVELOPE_SAMPLES);
}

function spinStep(run: RunState, now: number, sample: readonly number[], config: GuardConfig): boolean {
	const fresh = run.freshUpdates;
	const text = run.pendingText;
	run.freshUpdates = 0;
	run.pendingText = null;
	if (fresh > 0 && text !== null) {
		const stats = dominantLineStats(text);
		if (!isRepetitive(stats, config)) {
			run.spinSince = 0;
			return false;
		}
		run.dominant = stats;
		run.repetitiveAt = now;
	}
	if (run.repetitiveAt === 0 || now - run.repetitiveAt > Math.max(config.rateWindowMs, 2 * config.tickMs)) {
		run.spinSince = 0;
		return false;
	}
	const base = run.timeline.indexAtOrBefore(now - config.rateWindowMs);
	if (base < 0) {
		run.spinSince = 0;
		return false;
	}
	const span = (now - run.timeline.value(base, AT)) / 1000;
	if (span < config.rateWindowMs / 1000) {
		run.spinSince = 0;
		return false;
	}
	run.outRate = (sample[SAMPLE_WRITTEN] - run.timeline.value(base, WRITTEN)) / span;
	run.inRate = (sample[SAMPLE_READ] - run.timeline.value(base, READ)) / span;
	if (run.outRate < config.minOutBytesPerSec || run.inRate > config.maxInBytesPerSec) {
		run.spinSince = 0;
		return false;
	}
	if (run.spinSince === 0) run.spinSince = now;
	return now - run.spinSince >= config.spinWindowSec * 1000;
}

function suspectStep(run: RunState, now: number, sample: readonly number[], config: GuardConfig): void {
	if (run.spinSuspect || config.spinSuspectSec <= 0) return;
	const base = run.timeline.indexAtOrBefore(now - config.rateWindowMs);
	if (base < 0) return;
	const span = (now - run.timeline.value(base, AT)) / 1000;
	if (span < config.rateWindowMs / 1000) return;
	const cores = (sample[SAMPLE_CPU] - run.timeline.value(base, CPU)) / (span * 1e6);
	if (cores < 1 - CORES_BAND || cores > 1 + CORES_BAND) {
		run.suspectSince = 0;
		return;
	}
	if (run.suspectSince === 0) run.suspectSince = now;
	if (now - run.suspectSince < config.spinSuspectSec * 1000) return;
	const range = envelopeRange(run, now, config.spinSuspectSec * 1000);
	if (range === null || range.max - range.min > Math.max(FLAT_BYTES, sample[SAMPLE_ANON] * FLAT_FRACTION)) {
		run.suspectSince = 0;
		return;
	}
	run.spinSuspect = true;
	run.suspectAt = now;
}

export function envelopeRange(run: RunState, now: number, windowMs: number): { min: number; max: number } | null {
	let min = Number.POSITIVE_INFINITY;
	let max = Number.NEGATIVE_INFINITY;
	let seen = 0;
	for (let index = 0; index < run.envelopeCount; index += 1) {
		const slot = (run.envelopeHead - 1 - index + ENVELOPE_SAMPLES) % ENVELOPE_SAMPLES;
		if (run.envelopeAt[slot] < now - windowMs) break;
		if (run.envelopeMin[slot] < min) min = run.envelopeMin[slot];
		if (run.envelopeMax[slot] > max) max = run.envelopeMax[slot];
		seen += 1;
	}
	return seen === 0 ? null : { min, max };
}

export function leakSlopeOf(run: RunState, now: number, config: GuardConfig): number | null {
	if (run.envelopeCount < 2) return null;
	const newest = (run.envelopeHead - 1 + ENVELOPE_SAMPLES) % ENVELOPE_SAMPLES;
	let oldest = -1;
	for (let index = 0; index < run.envelopeCount; index += 1) {
		const slot = (run.envelopeHead - 1 - index + ENVELOPE_SAMPLES) % ENVELOPE_SAMPLES;
		if (run.envelopeAt[slot] < now - config.leakWindowSec * 1000) break;
		oldest = slot;
	}
	if (oldest < 0) return null;
	const span = (run.envelopeAt[newest] - run.envelopeAt[oldest]) / 1000;
	if (span < config.leakWindowSec * 0.9) return null;
	let previous = Number.NEGATIVE_INFINITY;
	for (let slot = oldest; ; slot = (slot + 1) % ENVELOPE_SAMPLES) {
		if (run.envelopeMin[slot] < previous - ENVELOPE_TOLERANCE_BYTES) return null;
		previous = run.envelopeMin[slot];
		if (slot === newest) break;
	}
	return (run.envelopeMin[newest] - run.envelopeMin[oldest]) / span;
}

export function finalizeRun(run: RunState, now: number, oomNow: number, failed: boolean, exitCode: number | null, config: GuardConfig): Verdict {
	const base = run.timeline.indexAtOrBefore(now - OOM_RECENT_MS);
	const oomBase = base >= 0 ? run.timeline.value(base, OOM) : run.timeline.length > 0 ? run.timeline.value(0, OOM) : run.oomBase;
	run.leakSlope = leakSlopeOf(run, now, config);
	const span = run.timeline.length >= 2 ? run.timeline.value(run.timeline.length - 1, AT) - run.timeline.value(0, AT) : 0;
	run.avgCores = span > 0 ? (run.timeline.value(run.timeline.length - 1, CPU) - run.timeline.value(0, CPU)) / (span * 1000) : 0;
	let verdict: Verdict = "normal";
	if (run.killed === "spin") verdict = "spin";
	else if (run.killed === "ceiling" || (oomNow > oomBase && exitCode === SIGKILL_EXIT)) verdict = "accumulate";
	else if (run.leakSlope !== null && run.leakSlope >= config.leakBytesPerSec) verdict = "leak-suspect";
	else if (run.spinSuspect) verdict = "spin-suspect";
	else if (run.peakAnon >= config.bigAnonBytes) verdict = "legit-big";
	run.verdict = verdict;
	return verdict;
}

function mb(bytes: number): number {
	return Math.round(bytes / (1024 * 1024));
}

function gb(bytes: number): string {
	return (bytes / (1024 * 1024 * 1024)).toFixed(1);
}

function sec(ms: number): string {
	return `${Math.round(ms / 1000)}s`;
}

export function annotationFor(run: RunState, config: GuardConfig, durationMs: number, wrapFailed: boolean): string | null {
	if (wrapFailed) return "[pi-guard] 隔离包装未能启动,已降级为仅观测模式;本条命令没有执行,请重试。";
	const limit = gb(config.sliceMax);
	switch (run.verdict) {
		case "spin": {
			const line = run.dominant ? run.dominant.topLine.slice(0, 60) : "";
			return `[pi-guard] 已停止:空转热循环——${sec(run.spinProofMs)} 内持续重复输出同一行「${line}」(输出 ${Math.round(run.outRate / 1024)}KB/s,输入 ${Math.round(run.inRate / 1024)}KB/s),命令是无 timeout 的内联脚本。请修正循环的等待或退出条件后重跑,或给 bash 调用加 timeout 参数。`;
		}
		case "accumulate":
			return `[pi-guard] 已停止:内存涨到硬顶 ${limit}GB(峰值 ${mb(run.peakAnon)}MB),被内核终止。合法的大内存任务请分批或流式处理;非预期增长请排查泄漏。`;
		case "spin-suspect":
			return `[pi-guard] 提示(未干预):单核持续满载 ${sec(run.suspectAt - run.suspectSince)} 且内存持平,疑似空转;若是合法计算可忽略。`;
		case "leak-suspect":
			return `[pi-guard] 提示(未干预):内存持续缓涨(约 ${Math.round((run.leakSlope ?? 0) / (1024 * 1024))}MB/s,已持续 ${config.leakWindowSec}s,峰值 ${mb(run.peakAnon)}MB),疑似泄漏。`;
		case "legit-big":
			return `[pi-guard] 记录:大内存任务结束,峰值 ${mb(run.peakAnon)}MB(硬顶 ${limit}GB)。`;
		default:
			if (run.sampled && durationMs >= config.reportMinSec * 1000) {
				return `[pi-guard] 用量:峰值内存 ${mb(run.peakAnon)}MB/硬顶 ${limit}GB,平均 ${run.avgCores.toFixed(1)} 核,历时 ${sec(durationMs)}。`;
			}
	}
	return null;
}

export function foldRepetitive(text: string, config: GuardConfig): string | null {
	const cut = text.lastIndexOf("\n\nCommand ");
	const body = cut >= 0 ? text.slice(0, cut) : text;
	const stats = dominantLineStats(body);
	if (!isRepetitive(stats, config)) return null;
	const folded = `…(${stats.topCount} 行重复「${stats.topLine.slice(0, 80)}」,pi-guard 已折叠)…`;
	return cut >= 0 ? `${folded}${text.slice(cut)}` : folded;
}

export function shouldLog(run: RunState, durationMs: number, mode: string): boolean {
	return durationMs >= LOG_MIN_DURATION_MS || run.verdict !== "normal" || mode !== "contained";
}

export function logEntryFor(run: RunState, config: GuardConfig, durationMs: number, mode: string, leftover: boolean): string {
	const head = run.original.replace(/\s+/g, " ").slice(0, CMD_LOG_CHARS);
	return JSON.stringify({
		ts: new Date().toISOString(),
		verdict: run.verdict,
		action: run.killed === "spin" ? "kill-spin" : run.killed === "ceiling" ? "kill-ceiling" : run.verdict === "accumulate" ? "kernel-oom" : "none",
		durationMs,
		peakAnonMB: mb(run.peakAnon),
		avgCores: Math.round(run.avgCores * 100) / 100,
		outKBps: Math.round(run.outRate / 1024),
		inKBps: Math.round(run.inRate / 1024),
		mode,
		leftover,
		unit: run.unit,
		cmd: head,
	});
}

export type ProcRow = { pid: number; ppid: number; pgrp: number; session: number; start: number; cpuUs: number };

export function processTree(rootPid: number, rows: ProcRow[]): ProcRow[] {
	const children = new Map<number, number[]>();
	for (const row of rows) {
		const siblings = children.get(row.ppid);
		if (siblings) siblings.push(row.pid);
		else children.set(row.ppid, [row.pid]);
	}
	const pids = [rootPid];
	for (let index = 0; index < pids.length; index += 1) {
		const siblings = children.get(pids[index]);
		if (siblings) pids.push(...siblings);
	}
	const wanted = new Set(pids);
	return rows.filter((row) => wanted.has(row.pid));
}

export function isSessionLeaderChild(row: ProcRow, parentPid: number): boolean {
	return row.ppid === parentPid && row.pgrp === row.pid && row.session === row.pid;
}

export function startedAtMs(row: ProcRow, bootMs: number): number {
	return bootMs + (row.start * CLOCK_TICK_US) / 1000;
}

export function freshSessionLeaders(rows: ProcRow[], parentPid: number, sinceMs: number, bootMs: number, known: ReadonlySet<number>): ProcRow[] {
	return rows.filter((row) => isSessionLeaderChild(row, parentPid) && !known.has(row.pid) && startedAtMs(row, bootMs) >= sinceMs - START_SLACK_MS);
}

type NotifyType = "info" | "warning" | "error";
type GuardContext = { hasUI: boolean; ui: { notify(message: string, type?: NotifyType): void } };
type Tracked = { run: RunState; ctx: GuardContext | null; scopeDir: string; known: Set<number> | null; wrapFailed: boolean; leftover: boolean; suspectNotified: boolean };
type Mode = "disabled" | "probing" | "contained" | "observed";
type ContentPart = { type: string; text?: string };

const IO_MAX_PIDS = 64;
const MODE_LABEL: Record<Mode, string> = {
	disabled: "已禁用",
	probing: "探测隔离能力中",
	contained: "cgroup 隔离",
	observed: "仅观测(用户态兜底)",
};
let bootMs: number | null = null;

function readText(path: string): string | null {
	try {
		return readFileSync(path, "utf8");
	} catch {
		return null;
	}
}

function bootTimeMs(): number {
	if (bootMs !== null) return bootMs;
	const stat = readText(`${PROC_ROOT}/stat`);
	const at = stat?.indexOf("\nbtime ") ?? -1;
	bootMs = stat === null || at < 0 ? -1 : Number(stat.slice(at + 7, stat.indexOf("\n", at + 7))) * 1000;
	return bootMs;
}

function pidsIn(dir: string): number[] {
	const text = readText(join(dir, "cgroup.procs"));
	if (text === null) return [];
	const pids: number[] = [];
	for (const word of text.split(/\s+/)) {
		const pid = Number(word);
		if (pid > 0) pids.push(pid);
	}
	return pids;
}

function writeCgroup(dir: string, file: string, value: string): void {
	try {
		writeFileSync(join(dir, file), value);
	} catch {}
}

function ensureLimit(dir: string, file: string, value: string): void {
	if ((readText(join(dir, file)) ?? "").trim() !== value) writeCgroup(dir, file, value);
}

function procRows(): ProcRow[] {
	const rows: ProcRow[] = [];
	let names: string[];
	try {
		names = readdirSync(PROC_ROOT);
	} catch {
		return rows;
	}
	for (const name of names) {
		const first = name.charCodeAt(0);
		if (first < 48 || first > 57) continue;
		const stat = readText(`${PROC_ROOT}/${name}/stat`);
		if (stat === null) continue;
		const fields = stat.slice(stat.lastIndexOf(")") + 2).split(" ");
		rows.push({
			pid: Number(name),
			ppid: Number(fields[1]),
			pgrp: Number(fields[2]),
			session: Number(fields[3]),
			start: Number(fields[19]),
			cpuUs: (Number(fields[11]) + Number(fields[12])) * CLOCK_TICK_US,
		});
	}
	return rows;
}

function sessionLeaderChildren(): Set<number> | null {
	const boot = bootTimeMs();
	if (boot < 0) return null;
	return new Set(procRows().filter((row) => isSessionLeaderChild(row, process.pid)).map((row) => row.pid));
}

function argvTail(pid: number): string | null {
	const raw = readText(`${PROC_ROOT}/${pid}/cmdline`);
	if (raw === null || !raw.endsWith("\0")) return null;
	const parts = raw.split("\0");
	return parts[parts.length - 2] ?? null;
}

function exitCodeOf(structuredContent: unknown): number | null {
	if (typeof structuredContent !== "object" || structuredContent === null) return null;
	const code = (structuredContent as { exit_code?: unknown }).exit_code;
	return typeof code === "number" ? code : null;
}

export function configPath(): string {
	return process.env.PI_GUARD_CONFIG ?? join(homedir(), ".pi", "agent", "pi-guard.json");
}

export function loadConfig(path: string): GuardConfig {
	let raw: unknown = null;
	const text = readText(path);
	if (text !== null) {
		try {
			raw = JSON.parse(text);
		} catch {}
	}
	const config = mergeConfig(raw);
	config.sliceMax = sliceMaxBytesFor(totalmem(), config);
	return config;
}

export function recentLogLines(logFile: string, limit: number): string[] {
	const text = readText(logFile);
	if (text === null) return [];
	const lines: string[] = [];
	for (const raw of text.split("\n")) {
		if (raw === "") continue;
		try {
			const entry = JSON.parse(raw) as { ts?: string; verdict?: string; action?: string; durationMs?: number; peakAnonMB?: number; cmd?: string };
			lines.push(`${(entry.ts ?? "").slice(11, 19)} ${entry.verdict ?? "?"} ${entry.action ?? "?"} ${entry.durationMs ?? 0}ms peak=${entry.peakAnonMB ?? 0}MB ${(entry.cmd ?? "").slice(0, 60)}`);
		} catch {}
	}
	return lines.slice(-limit);
}

export class Guard {
	readonly config: GuardConfig;
	readonly logFile: string;
	mode: Mode = "probing";
	sliceDir = "";
	private readonly instance = randomBytes(3).toString("hex");
	private seq = 0;
	private readonly tracked = new Map<string, Tracked>();
	private ticker: ReturnType<typeof setInterval> | null = null;
	private reprobe: ReturnType<typeof setTimeout> | null = null;

	constructor(pi: ExtensionAPI, config: GuardConfig, logDir: string) {
		this.config = config;
		this.logFile = join(logDir, "log.jsonl");
		pi.registerCommand("guard", {
			description: "显示 pi-guard 隔离模式、硬顶与最近裁决",
			handler: async (_args, ctx) => {
				ctx.ui.notify(this.statusText(), "info");
			},
		});
		if (!config.enabled) {
			this.mode = "disabled";
			return;
		}
		pi.on("tool_call", (event, ctx) => {
			if (event.toolName === "bash") this.begin(event.toolCallId, event.input, ctx as unknown as GuardContext);
		});
		pi.on("tool_execution_update", (event) => {
			if (event.toolName === "bash") this.observeOutput(event.toolCallId, event.partialResult);
		});
		pi.on("tool_result", (event) => {
			if (event.toolName !== "bash") return undefined;
			return this.annotate(event.toolCallId, event.content, event.structuredContent, event.isError) as ToolResultEventResult | undefined;
		});
		pi.on("tool_execution_end", (event) => {
			if (event.toolName === "bash") this.finish(event.toolCallId, event.isError, event.durationMs);
		});
		pi.on("session_shutdown", () => {
			this.stopTicker();
			if (this.reprobe !== null) {
				clearTimeout(this.reprobe);
				this.reprobe = null;
			}
		});
		const capable = [config.systemdRun, ENV_BIN, config.bash, join(CGROUP_ROOT, "cgroup.controllers")].every((path) => existsSync(path));
		if (capable) this.probe();
		else this.mode = "observed";
	}

	private begin(toolCallId: string, input: { command?: unknown; timeout?: unknown }, ctx: GuardContext | null): void {
		const command = input.command;
		if (typeof command !== "string" || command === "" || isWrapped(command)) return;
		const now = Date.now();
		let unit = "";
		let wrapped: string | null = null;
		if (this.mode === "contained") {
			const candidate = nextUnitName(process.pid, this.instance, (this.seq += 1));
			const candidateCommand = wrapCommand(command, candidate, this.config);
			if (wrapFits(candidateCommand)) {
				wrapped = candidateCommand;
				unit = candidate;
			}
		}
		const contained = unit !== "";
		const run = createRunState({
			toolCallId,
			unit,
			original: command,
			spinEligible: isInlineScript(command) && !isExplicitlyBounded(command, input.timeout),
			contained,
			startedAt: now,
		});
		run.oomBase = this.sliceOomKill();
		const entry: Tracked = {
			run,
			ctx,
			scopeDir: contained ? join(this.sliceDir, `${unit}.scope`) : "",
			known: contained ? null : sessionLeaderChildren(),
			wrapFailed: false,
			leftover: false,
			suspectNotified: false,
		};
		this.tracked.set(toolCallId, entry);
		if (wrapped !== null) input.command = wrapped;
		void this.locate(entry);
	}

	private attached(entry: Tracked): boolean {
		const run = entry.run;
		if (!run.contained) return this.findShell(entry) !== 0;
		if (run.scopeSeen) return true;
		if (!existsSync(join(entry.scopeDir, "cgroup.procs"))) return false;
		run.scopeSeen = true;
		this.enforceSlice();
		if ((readText(join(entry.scopeDir, "memory.oom.group")) ?? "").trim() !== "1") writeCgroup(entry.scopeDir, "memory.oom.group", "1");
		return true;
	}

	private async locate(entry: Tracked): Promise<void> {
		const deadline = Date.now() + SCOPE_WAIT_MS;
		while (!entry.run.done && Date.now() < deadline && !this.attached(entry)) {
			await new Promise((resolve) => setTimeout(resolve, SCOPE_POLL_MS));
		}
		if (entry.run.done) return;
		this.sampleAll();
		this.startTicker();
	}

	private findShell(entry: Tracked): number {
		const run = entry.run;
		if (run.shellPid !== 0) return run.shellPid;
		const boot = bootTimeMs();
		if (boot < 0) return 0;
		const candidates = freshSessionLeaders(procRows(), process.pid, run.startedAt, boot, entry.known ?? new Set<number>());
		const exact = candidates.filter((row) => argvTail(row.pid) === run.original);
		if (exact.length > 0) run.shellPid = exact[exact.length - 1].pid;
		else if (candidates.length === 1) run.shellPid = candidates[0].pid;
		return run.shellPid;
	}

	private sliceOomKill(): number {
		if (this.sliceDir === "") return 0;
		return flatValue(readText(join(this.sliceDir, "memory.events")) ?? "", "oom_kill");
	}

	private enforceSlice(): void {
		ensureLimit(this.sliceDir, "memory.max", String(this.config.sliceMax));
		ensureLimit(this.sliceDir, "memory.swap.max", "0");
	}

	private sampleScope(entry: Tracked, oom: number): readonly number[] {
		const run = entry.run;
		const pids = pidsIn(entry.scopeDir);
		let read = 0;
		let written = 0;
		if (run.spinEligible || pids.length <= IO_MAX_PIDS) {
			for (const pid of pids) {
				const io = readText(`${PROC_ROOT}/${pid}/io`);
				if (io === null) continue;
				read += flatValue(io, "rchar:");
				written += flatValue(io, "wchar:");
			}
		}
		const stat = readText(join(entry.scopeDir, "memory.stat"));
		const cpu = readText(join(entry.scopeDir, "cpu.stat"));
		return [stat === null ? run.lastAnon : flatValue(stat, "anon"), cpu === null ? run.lastCpu : flatValue(cpu, "usage_usec"), read, written, oom];
	}

	private sampleTree(entry: Tracked, oom: number): readonly number[] {
		const run = entry.run;
		let anon = 0;
		let cpu = 0;
		let read = 0;
		let written = 0;
		for (const row of processTree(run.shellPid, procRows())) {
			const status = readText(`${PROC_ROOT}/${row.pid}/status`);
			if (status !== null) anon += flatValue(status, "RssAnon:") * 1024;
			cpu += row.cpuUs;
			if (!run.spinEligible) continue;
			const io = readText(`${PROC_ROOT}/${row.pid}/io`);
			if (io === null) continue;
			read += flatValue(io, "rchar:");
			written += flatValue(io, "wchar:");
		}
		return [anon, cpu, read, written, oom];
	}

	private sampleAll(): void {
		if (this.mode === "contained") this.enforceSlice();
		const oom = this.sliceOomKill();
		for (const entry of this.tracked.values()) {
			if (entry.run.done) continue;
			try {
				this.sampleEntry(entry, oom);
			} catch {}
		}
	}

	private sampleEntry(entry: Tracked, oom: number): void {
		const run = entry.run;
		if (!this.attached(entry)) return;
		const sample = run.contained ? this.sampleScope(entry, oom) : this.sampleTree(entry, oom);
		const action = stepRun(run, Date.now(), sample, this.config);
		if (action === "kill-spin") this.kill(entry, "spin");
		else if (action === "kill-ceiling") this.kill(entry, "ceiling");
		if (run.spinSuspect && !entry.suspectNotified) {
			entry.suspectNotified = true;
			this.notify(entry, "[pi-guard] 提示(未干预):一条命令单核持续满载且内存持平,疑似空转。", "warning");
		}
	}

	private observeOutput(toolCallId: string, partialResult: { content?: { text?: unknown }[] } | null | undefined): void {
		const entry = this.tracked.get(toolCallId);
		if (entry === undefined || !entry.run.spinEligible) return;
		const text = partialResult?.content?.[0]?.text;
		if (typeof text !== "string" || text === "") return;
		entry.run.freshUpdates += 1;
		entry.run.pendingText = text;
	}

	private annotate<P extends ContentPart>(toolCallId: string, content: ReadonlyArray<P>, structuredContent: unknown, isError: boolean) {
		const entry = this.tracked.get(toolCallId);
		if (entry === undefined) return undefined;
		const run = entry.run;
		const now = Date.now();
		const durationMs = now - run.startedAt;
		const first = content.find((part) => part.type === "text" && typeof part.text === "string");
		if (run.contained && first !== undefined && isWrapFailure(first.text ?? "", isError, durationMs, run.scopeSeen)) {
			entry.wrapFailed = true;
			this.probeFailed();
		}
		finalizeRun(run, now, this.sliceOomKill(), isError, exitCodeOf(structuredContent), this.config);
		const note = annotationFor(run, this.config, durationMs, entry.wrapFailed);
		const folded = run.verdict === "spin" && first !== undefined ? foldRepetitive(first.text ?? "", this.config) : null;
		if (note === null && folded === null) return undefined;
		const parts: Array<P | { type: "text"; text: string }> = content.map((part) => (part === first && folded !== null ? { type: "text", text: folded } : part));
		if (note !== null) parts.push({ type: "text", text: note });
		return structuredContent === undefined ? { content: parts } : { content: parts, structuredContent };
	}

	private finish(toolCallId: string, isError: boolean, durationMs: number | undefined): void {
		const entry = this.tracked.get(toolCallId);
		if (entry === undefined) return;
		this.tracked.delete(toolCallId);
		const run = entry.run;
		run.done = true;
		const elapsed = typeof durationMs === "number" ? durationMs : Date.now() - run.startedAt;
		if (run.contained && run.scopeSeen) entry.leftover = pidsIn(entry.scopeDir).length > 0;
		if (run.verdict === null) finalizeRun(run, Date.now(), this.sliceOomKill(), isError, null, this.config);
		const mode = run.contained ? "contained" : "observed";
		if (run.sampled && shouldLog(run, elapsed, mode)) this.appendLog(logEntryFor(run, this.config, elapsed, mode, entry.leftover));
		if (this.tracked.size === 0) this.stopTicker();
	}

	private kill(entry: Tracked, kind: KillKind): void {
		const run = entry.run;
		if (run.contained) writeCgroup(entry.scopeDir, "cgroup.kill", "1");
		else this.killTree(run);
		const message = kind === "spin"
			? "[pi-guard] 已停止一条空转热循环命令(持续重复输出同一行且不读输入)。"
			: `[pi-guard] 已停止一条触到内存硬顶(${gb(this.config.sliceMax)}GB)的命令。`;
		this.notify(entry, message, "warning");
	}

	private killTree(run: RunState): void {
		for (const row of processTree(run.shellPid, procRows())) {
			try {
				process.kill(row.pid, "SIGKILL");
			} catch {}
		}
		try {
			process.kill(-run.shellPid, "SIGKILL");
		} catch {}
	}

	private notify(entry: Tracked, message: string, type: NotifyType): void {
		if (entry.ctx === null || !entry.ctx.hasUI) return;
		try {
			entry.ctx.ui.notify(message, type);
		} catch {}
	}

	private startTicker(): void {
		if (this.ticker !== null) return;
		this.ticker = setInterval(() => this.sampleAll(), this.config.tickMs);
		this.ticker.unref?.();
	}

	private stopTicker(): void {
		if (this.ticker === null) return;
		clearInterval(this.ticker);
		this.ticker = null;
	}

	private probe(): void {
		if (this.mode === "disabled") return;
		this.mode = "probing";
		let output = "";
		let settled = false;
		let timer: ReturnType<typeof setTimeout> | undefined;
		const settle = (ok: boolean): void => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			if (ok) this.acceptProbe(output);
			else this.probeFailed();
		};
		try {
			const unit = `${nextUnitName(process.pid, this.instance, (this.seq += 1))}-probe`;
			const child = spawn(this.config.systemdRun, ["--user", "--scope", "--quiet", "--collect", `--unit=${unit}`, `--slice=${this.config.slice}`, "-p", "MemorySwapMax=0", "-p", `TasksMax=${TASKS_MAX}`, "--", "/bin/sh", "-c", "cat /proc/self/cgroup"], {
				stdio: ["ignore", "pipe", "ignore"],
			});
			timer = setTimeout(() => {
				child.kill("SIGKILL");
				settle(false);
			}, PROBE_TIMEOUT_MS);
			timer.unref?.();
			child.stdout?.on("data", (chunk: string) => {
				output += chunk;
			});
			child.on("error", () => settle(false));
			child.on("exit", (code) => settle(code === 0));
		} catch {
			this.probeFailed();
		}
	}

	private acceptProbe(output: string): void {
		const match = /^0::(\S+)/m.exec(output);
		const dir = match === null ? "" : join(CGROUP_ROOT, dirname(match[1]));
		if (dir === "" || !existsSync(join(dir, "cgroup.procs"))) {
			this.probeFailed();
			return;
		}
		this.sliceDir = dir;
		this.mode = "contained";
		this.enforceSlice();
		if (this.reprobe !== null) {
			clearTimeout(this.reprobe);
			this.reprobe = null;
		}
	}

	private probeFailed(): void {
		this.mode = "observed";
		if (this.reprobe !== null) return;
		this.reprobe = setTimeout(() => {
			this.reprobe = null;
			this.probe();
		}, REPROBE_MS);
		this.reprobe.unref?.();
	}

	private appendLog(line: string): void {
		try {
			mkdirSync(dirname(this.logFile), { recursive: true });
			let size = 0;
			try {
				size = statSync(this.logFile).size;
			} catch {}
			if (size > LOG_ROTATE_BYTES) renameSync(this.logFile, `${this.logFile}.1`);
			appendFileSync(this.logFile, `${line}\n`, { mode: 0o600 });
		} catch {}
	}

	statusText(): string {
		const config = this.config;
		const lines = [
			`pi-guard:${MODE_LABEL[this.mode]} | 硬顶 ${gb(config.sliceMax)}GB(总内存的 ${Math.round((config.sliceMax / totalmem()) * 100)}%,禁用交换区) | slice ${this.sliceDir || config.slice}`,
			`空转即停:无 timeout 的内联脚本,连续 ${config.spinWindowSec}s 重复输出同一行(≥${Math.round(config.repeatFrac * 100)}%)且输出 ≥${Math.round(config.minOutBytesPerSec / 1024)}KB/s 且读入 ≤${Math.round(config.maxInBytesPerSec / 1024)}KB/s`,
			`只记录不停:单核满载 ${config.spinSuspectSec}s 且内存持平(疑似空转);内存每秒缓涨 ≥${Math.round(config.leakBytesPerSec / (1024 * 1024))}MB 持续 ${config.leakWindowSec}s(疑似泄漏);峰值 ≥${mb(config.bigAnonBytes)}MB 且正常结束(合法大内存)`,
			`日志 ${this.logFile}`,
			...recentLogLines(this.logFile, LOG_SHOW_LINES),
		];
		return lines.join("\n");
	}
}

export function logDirPath(): string {
	return process.env.PI_GUARD_LOG_DIR ?? join(homedir(), ".pi", "agent", "pi-guard");
}

export default function (pi: ExtensionAPI): void {
	new Guard(pi, loadConfig(configPath()), logDirPath());
}
