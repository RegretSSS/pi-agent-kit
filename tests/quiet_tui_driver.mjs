import { register } from "node:module";
import { pathToFileURL } from "node:url";
register("./pi_packages_hook.mjs", import.meta.url);
import { readFileSync } from "node:fs";
import { join } from "node:path";
import * as quiet from "../extensions/quiet-tui.ts";

const [scenario] = process.argv.slice(2);
const spec = scenario === "pure" ? {} : JSON.parse(readFileSync(0, "utf8"));
const COLOR_CODES = /\x1b\[[0-9;]*m/g;
const unstyled = (line) => line.replace(COLOR_CODES, "");
const htmlText = (html) => (html ?? "").replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&").replace(/&quot;/g, '"').trim();
const cwd = process.cwd();

async function loadPi() {
	const root = process.env.PI_PACKAGE_ROOT;
	if (!root) throw new Error("PI_PACKAGE_ROOT 未设置");
	const load = (relative) => import(pathToFileURL(join(root, relative)).href);
	const kit = {
		pi: await load("dist/index.js"),
		piTui: await load("node_modules/@earendil-works/pi-tui/dist/index.js"),
		nativeRenderers: await load("dist/core/tools/renderers/index.js"),
		mcpTools: await load("dist/extensions/mcp/tools.js"),
		exportTool: await load("dist/core/export-html/tool-renderer.js"),
	};
	kit.theme = (await load("dist/modes/interactive/theme/theme.js")).theme;
	kit.pi.initTheme("dark", false);
	return kit;
}

async function captureResolver() {
	let resolver;
	await quiet.default({ registerToolRenderer: (candidate) => (resolver = candidate) });
	return resolver;
}

function definition(kit, kind, toolName) {
	if (kind === "unregistered") return undefined;
	if (kind === "plain") return { name: toolName };
	if (kind === "custom") {
		return {
			name: toolName,
			renderCall: () => new kit.piTui.Text("custom call row", 0, 0),
			renderResult: () => new kit.piTui.Text("custom result row", 0, 0),
		};
	}
	if (kind === "mcp") return { name: toolName, ...kit.mcpTools.createMcpToolRenderers("docs/search") };
	return kit.nativeRenderers.withBuiltInRenderers(toolName, undefined);
}

const textResult = (text, isError = false) => ({ content: [{ type: "text", text }], isError, durationMs: 1234 });

function snapshot(component) {
	const lines = component.render(100);
	return { rows: lines.length, text: lines.map(unstyled) };
}

function play(kit, scene, resolver) {
	const native = definition(kit, scene.def, scene.toolName);
	const resolved = resolver(scene.toolName, () => native);
	const component = new kit.pi.ToolExecutionComponent(scene.toolName, `call_${scene.name}`, scene.args, { outputPad: 1 }, resolved, { requestRender() {} }, cwd);
	if (scene.expanded) component.setExpanded(true);
	const before = snapshot(component);
	component.markExecutionStarted();
	component.setArgsComplete();
	let running;
	if (scene.partial !== undefined) {
		component.updateResult(textResult(scene.partial), true);
		running = snapshot(component);
	}
	component.updateResult(textResult(scene.result.text, scene.result.isError), false);
	return { passthrough: resolved === native, before, running, final: snapshot(component) };
}

function exportPage(kit, scene, resolver) {
	const renderer = kit.exportTool.createToolHtmlRenderer({
		getToolRenderers: (toolName) => resolver(toolName, () => definition(kit, scene.def, toolName)),
		theme: kit.theme,
		cwd,
		width: 100,
	});
	const callId = `call_${scene.name}`;
	const result = renderer.renderResult(callId, scene.toolName, [{ type: "text", text: scene.result.text }], {}, scene.result.isError);
	return {
		call: htmlText(renderer.renderCall(callId, scene.toolName, scene.args)),
		collapsed: htmlText(result?.collapsed),
		expanded: htmlText(result?.expanded),
		fallback: result === undefined,
	};
}

function pure() {
	return {
		sanitize: [quiet.sanitizeInline("a\x1b]0;pwn\x07b\nc\r\td\x1b[31me\x1b[0mf\x00g"), quiet.sanitizeInline("  x   y ")],
		compact: [quiet.compactArgs({ cmd: "sleep 4; echo X", name: "bg-e2e" }), quiet.compactArgs({ nested: { a: 1 }, list: [1, 2], skip: undefined, nil: null, long: "x".repeat(80) }), quiet.compactArgs("scalar"), quiet.compactArgs([1, "a b"])],
		duration: [0, 1_230, 59_949, 59_999, 60_000, 90_000, 3_599_600, 3_600_000, 7_199_400, 7_260_000].map(quiet.formatDuration),
		takesOver: [
			["bash", { renderCall() {}, renderResult() {} }],
			["mcp__x__y", { renderCall() {} }],
			["task_create", undefined],
			["task_create", { name: "task_create" }],
			["Agent", { renderCall() {}, renderResult() {} }],
			["custom", { renderCall() {} }],
			["custom", { renderResult() {} }],
		].map(([toolName, base]) => [toolName, quiet.takesOver(toolName, base)]),
		mcp: quiet.mcpLabel("mcp__docs__search"),
		path: quiet.shortenPath(`${process.env.HOME}/x/y`),
	};
}

let out = {};
if (scenario === "pure") out = { pure: pure() };
if (scenario === "render") {
	const [resolver, kit] = await Promise.all([captureResolver(), loadPi()]);
	out = { results: Object.fromEntries(spec.scenes.map((scene) => [scene.name, play(kit, scene, resolver)])) };
}
if (scenario === "export") {
	const [resolver, kit] = await Promise.all([captureResolver(), loadPi()]);
	out = { pages: Object.fromEntries(spec.scenes.map((scene) => [scene.name, exportPage(kit, scene, resolver)])) };
}
process.stdout.write(JSON.stringify(out));
