import { homedir } from "node:os";
import type { ExtensionAPI, ToolRenderers } from "@earendil-works/pi-coding-agent";
import type { Component } from "@earendil-works/pi-tui";

export const BUILTIN_TOOLS = new Set(["bash", "powershell", "read", "edit", "write", "grep", "find", "ls", "codemode"]);
export const MCP_PREFIX = "mcp__";
export const RUNNING_PREVIEW_ROWS = 3;
export const ARG_VALUE_CHARS = 60;
export const SHELL_PROMPTS: Record<string, string> = { bash: "$", powershell: "PS>" };
const OPERATING_SYSTEM_SEQUENCES = /\x1b\][^\x07]*(?:\x07|\x1b\\)/g;
const CONTROL_SEQUENCES = /\x1b\[[0-?]*[ -/]*[@-~]|\x1b[()][0-2A-Z]/g;
const LEFTOVER_CONTROL_CHARS = /[\x00-\x08\x0B-\x1F\x7F]/g;
const BLANK_RUNS = /\s+/g;
const ANY_BLANK = /\s/;
const CODEMODE_HEADER = /^(?:Script (?:completed|failed|error:)|Output:|Wall time [\d.]+ seconds)$/;
const CODEMODE_OPTIONS_LINE = /^\/\/ @options:/;
const NESTED_STATUS = new Map<string, readonly [string, string]>([["running", ["warning", "…"]], ["ok", ["success", "✓"]], ["error", ["error", "✗"]], ["cancelled", ["muted", "⊘"]]]);
const RUNNING_MARK: readonly [string, string] = ["warning", "…"];

export class DelegateToDefault extends Error {
	constructor(slot: "renderCall" | "renderResult") {
		super(`quiet-tui: ${slot} 委托 pi 默认渲染`);
	}
}

type RenderCall = NonNullable<ToolRenderers["renderCall"]>;
export type RenderContext = Parameters<RenderCall>[2];
type ThemeLike = { fg(color: string, text: string): string; bold(text: string): string };
type Tail = { truncateToWidth(text: string, maxWidth: number, ellipsis?: string): string };
export type NestedCall = { name?: unknown; status?: unknown; durationMs?: unknown };
type ResultLike = { content: Array<{ type: string; text?: string }>; details?: { calls?: NestedCall[] } };
type ContextLike = Pick<RenderContext, "argsComplete" | "isPartial" | "isError" | "durationMs" | "outputPad" | "expanded">;

export function sanitizeInline(text: string): string {
	return text.replace(OPERATING_SYSTEM_SEQUENCES, "").replace(CONTROL_SEQUENCES, "").replace(LEFTOVER_CONTROL_CHARS, "").replace(BLANK_RUNS, " ").trim();
}

function stringifyScalar(value: unknown): string {
	if (typeof value === "string") return value;
	try {
		return JSON.stringify(value) ?? String(value);
	} catch {
		return "[…]";
	}
}

function clip(flat: string): string {
	const points = Array.from(flat);
	return points.length > ARG_VALUE_CHARS ? `${points.slice(0, ARG_VALUE_CHARS - 1).join("")}…` : flat;
}

export function shortenValue(value: unknown): string {
	const raw = stringifyScalar(value);
	const flat = sanitizeInline(raw);
	if (!flat) return '""';
	const body = clip(flat);
	return typeof value === "string" && ANY_BLANK.test(raw) ? `"${body}"` : body;
}

export function compactArgs(args: unknown): string {
	if (args === null || typeof args !== "object" || Array.isArray(args)) return shortenValue(args);
	const parts: string[] = [];
	for (const [key, value] of Object.entries(args)) {
		if (value === undefined || value === null) continue;
		parts.push(`${sanitizeInline(key)}=${shortenValue(value)}`);
	}
	return parts.join(" ");
}

export function shortenPath(path: string): string {
	const home = homedir();
	return home && path.startsWith(home) ? `~${path.slice(home.length)}` : path;
}

export function mcpLabel(toolName: string): string {
	return toolName.slice(MCP_PREFIX.length).replace("__", "/");
}

export function callSummary(toolName: string, args: unknown, theme: ThemeLike): string {
	const record = args !== null && typeof args === "object" && !Array.isArray(args) ? (args as Record<string, unknown>) : {};
	const title = (label: string) => theme.fg("toolTitle", theme.bold(label));
	const accent = (text: string) => theme.fg("accent", text);
	const plain = (text: string) => theme.fg("toolOutput", text);
	const text = (value: unknown, fallback: string) => sanitizeInline(String(value ?? "")) || fallback;
	if (toolName in SHELL_PROMPTS) {
		const timeout = typeof record.timeout === "number" ? plain(` (timeout ${record.timeout}s)`) : "";
		return `${title(SHELL_PROMPTS[toolName])} ${title(text(record.command, "..."))}${timeout}`;
	}
	if (toolName === "read") {
		const offset = typeof record.offset === "number" && record.offset > 0 ? record.offset : 1;
		const ranged = record.offset !== undefined || record.limit !== undefined;
		const range = ranged ? theme.fg("warning", `:${offset}${typeof record.limit === "number" ? `-${offset + record.limit - 1}` : ""}`) : "";
		return `${title("read")} ${accent(shortenPath(text(record.path, "...")))}${range}`;
	}
	if (toolName === "edit" || toolName === "write" || toolName === "ls") return `${title(toolName)} ${accent(shortenPath(text(record.path, ".")))}`;
	if (toolName === "grep" || toolName === "find") {
		const pattern = text(record.pattern, "");
		const glob = typeof record.glob === "string" ? plain(` (${sanitizeInline(record.glob)})`) : "";
		return `${title(toolName)} ${accent(toolName === "grep" ? `/${pattern}/` : pattern)}${plain(` in ${shortenPath(text(record.path, "."))}`)}${glob}`;
	}
	if (toolName === "codemode") {
		const lines = scriptLines(record.code);
		const rest = lines.length - 1;
		return `${title("codemode")} ${plain(clip(sanitizeInline(lines[0] ?? "")) || "…")}${rest > 0 ? theme.fg("muted", ` (+${rest} lines)`) : ""}`;
	}
	return `${title(toolName.startsWith(MCP_PREFIX) ? mcpLabel(toolName) : toolName)} ${plain(compactArgs(args))}`;
}

export function scriptLines(code: unknown): string[] {
	if (typeof code !== "string") return [];
	return meaningfulLines(code).filter((line) => !CODEMODE_OPTIONS_LINE.test(line));
}

export function formatDuration(ms: number): string {
	if (ms < 59_950) return `${(ms / 1000).toFixed(1)}s`;
	const totalSeconds = Math.round(ms / 1000);
	if (totalSeconds < 3600) return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
	const totalMinutes = Math.round(ms / 60_000);
	return `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m`;
}

export function statusSuffix(context: Pick<ContextLike, "argsComplete" | "isPartial" | "isError" | "durationMs">, theme: ThemeLike): string {
	if (!context.argsComplete) return theme.fg("muted", " …");
	if (context.isPartial) return "";
	const mark = theme.fg(context.isError ? "error" : "success", context.isError ? " ✗" : " ✓");
	return context.durationMs === undefined ? mark : `${mark} ${theme.fg("muted", formatDuration(context.durationMs))}`;
}

export function resultText(result: ResultLike): string {
	return result.content.find((part) => part.type === "text" && part.text)?.text ?? "";
}

function meaningfulLines(text: string): string[] {
	return text.split("\n").map((line) => line.trimEnd()).filter((line) => line.trim());
}

export function tailLines(text: string, rows: number): string[] {
	return meaningfulLines(text).slice(-rows);
}

export function firstLine(text: string): string {
	return meaningfulLines(text)[0] ?? "";
}

export function foldedResultLines(result: ResultLike, context: Pick<ContextLike, "isPartial" | "isError">, theme: ThemeLike): string[] {
	if (context.isPartial) return tailLines(resultText(result), RUNNING_PREVIEW_ROWS).map((line) => theme.fg("toolOutput", sanitizeInline(line)));
	if (context.isError) return [theme.fg("error", sanitizeInline(firstLine(resultText(result))) || theme.fg("error", "✗"))];
	return [];
}

function nestedCalls(result: ResultLike): NestedCall[] {
	return Array.isArray(result.details?.calls) ? result.details.calls : [];
}

function nestedDuration(ms: unknown): string {
	return typeof ms === "number" && ms > 0 ? (ms < 1000 ? `${Math.round(ms)}ms` : formatDuration(ms)) : "";
}

export function nestedCallProgress(calls: NestedCall[], theme: ThemeLike): string {
	if (calls.length === 0) return "";
	let failed = 0;
	for (const call of calls) if (call?.status === "error") failed++;
	const last = calls[calls.length - 1] ?? {};
	const [color, icon] = NESTED_STATUS.get(String(last.status)) ?? RUNNING_MARK;
	const duration = nestedDuration(last.durationMs);
	return `${theme.fg("muted", `${calls.length} call${calls.length === 1 ? "" : "s"}`)} · ${theme.fg(color, icon)} ${theme.fg("toolOutput", sanitizeInline(String(last.name ?? "?")))}${duration ? ` ${theme.fg("muted", duration)}` : ""}${failed > 0 ? ` ${theme.fg("error", `· ${failed} failed`)}` : ""}`;
}

export function codemodeFailure(result: ResultLike): string {
	for (const part of result.content) {
		if (part.type !== "text" || !part.text) continue;
		for (const raw of part.text.split("\n")) {
			const line = sanitizeInline(raw);
			if (line && !CODEMODE_HEADER.test(line)) return line;
		}
	}
	return "";
}

export function codemodeResultLines(result: ResultLike, context: Pick<ContextLike, "isPartial" | "isError">, theme: ThemeLike): string[] {
	if (context.isPartial) {
		const progress = nestedCallProgress(nestedCalls(result), theme);
		return progress ? [progress] : tailLines(resultText(result), RUNNING_PREVIEW_ROWS).map((line) => theme.fg("toolOutput", sanitizeInline(line)));
	}
	if (context.isError) return [theme.fg("error", codemodeFailure(result) || "✗")];
	return [];
}

export function takesOver(toolName: string, base: ToolRenderers | undefined): boolean {
	if (BUILTIN_TOOLS.has(toolName) || toolName.startsWith(MCP_PREFIX)) return true;
	return !base?.renderCall && !base?.renderResult;
}

export class RenderedRow implements Component {
	private lines: string[] = [];
	private pad = 0;
	private cache: { lines: string[]; pad: number; width: number; output: string[] } | undefined;
	private tail: Tail;

	constructor(tail: Tail) {
		this.tail = tail;
	}

	setLines(lines: string[], pad: number) {
		if (lines === this.lines && pad === this.pad) return;
		this.lines = lines;
		this.pad = pad;
		this.cache = undefined;
	}

	invalidate() {
		this.cache = undefined;
	}

	render(width: number): string[] {
		if (this.cache && this.cache.lines === this.lines && this.cache.pad === this.pad && this.cache.width === width) return this.cache.output;
		const room = Math.max(1, width - this.pad - 1);
		const prefix = " ".repeat(this.pad);
		const output = this.lines.map((line) => prefix + this.tail.truncateToWidth(line, room, "…"));
		this.cache = { lines: this.lines, pad: this.pad, width, output };
		return output;
	}
}

export class PaddedFrame implements Component {
	private cache: { width: number; output: string[] } | undefined;
	readonly inner: Component;
	private pad: number;

	constructor(inner: Component, pad: number) {
		this.inner = inner;
		this.pad = pad;
	}

	invalidate() {
		this.cache = undefined;
		this.inner.invalidate();
	}

	render(width: number): string[] {
		if (this.cache && this.cache.width === width) return this.cache.output;
		const prefix = " ".repeat(this.pad);
		const output = this.inner.render(Math.max(1, width - this.pad)).map((line) => prefix + line);
		this.cache = { width, output };
		return output;
	}
}

export function createQuietRenderers(toolName: string, base: ToolRenderers | undefined, tail: Tail): ToolRenderers {
	const renderer = (slot: "renderCall" | "renderResult") => (base?.[slot] as ((...args: unknown[]) => Component) | undefined);
	const innerComponent = (last: Component | undefined): Component | undefined => (last instanceof PaddedFrame ? last.inner : last instanceof RenderedRow ? undefined : last);
	const row = (last: Component | undefined) => (last instanceof RenderedRow ? last : new RenderedRow(tail));
	const resultLines = toolName === "codemode" ? codemodeResultLines : foldedResultLines;
	return {
		renderShell: "self",
		renderCall(args, theme, context) {
			if (context.expanded) {
				const call = renderer("renderCall");
				if (!call) throw new DelegateToDefault("renderCall");
				return call(args, theme, { ...context, lastComponent: innerComponent(context.lastComponent) });
			}
			const target = row(context.lastComponent);
			target.setLines([callSummary(toolName, args, theme) + statusSuffix(context, theme)], context.outputPad);
			return target;
		},
		renderResult(result, options, theme, context) {
			if (options.expanded) {
				const render = renderer("renderResult");
				if (!render) throw new DelegateToDefault("renderResult");
				return new PaddedFrame(render(result, options, theme, { ...context, lastComponent: innerComponent(context.lastComponent) }), context.outputPad);
			}
			const target = row(context.lastComponent);
			target.setLines(resultLines(result, context, theme), context.outputPad);
			return target;
		},
	};
}

export default async function (pi: ExtensionAPI) {
	const { truncateToWidth } = await import("@earendil-works/pi-tui");
	const tail: Tail = { truncateToWidth };
	pi.registerToolRenderer((toolName, next) => {
		const base = next();
		return takesOver(toolName, base) ? createQuietRenderers(toolName, base, tail) : base;
	});
}
