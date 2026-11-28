import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SLEEP_LIMIT_SECONDS = 100;

const BARE_SLEEP = /\bsleep\s+(\d+(?:\.\d+)?)([smhd]?)\b/g;

function parseSleepSeconds(value: string, suffix: string): number {
	const n = parseFloat(value);
	if (Number.isNaN(n)) return 0;
	if (suffix === "s" || suffix === "") return n;
	if (suffix === "m") return n * 60;
	if (suffix === "h") return n * 3600;
	if (suffix === "d") return n * 86400;
	return n;
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", (event) => {
		if (event.toolName !== "bash") return;
		const command = (event.input as { command?: string })?.command;
		if (typeof command !== "string") return;
		BARE_SLEEP.lastIndex = 0;
		let match: RegExpExecArray | null;
		while ((match = BARE_SLEEP.exec(command)) !== null) {
			const seconds = parseSleepSeconds(match[1], match[2] ?? "");
			if (seconds > SLEEP_LIMIT_SECONDS) {
				return {
					block: true,
					reason: `裸 sleep ${match[1]}${match[2]}（${seconds}s）超过 ${SLEEP_LIMIT_SECONDS}s 上限，禁止阻塞会话。等待请用 task_create 后台任务或定时任务，到点自动唤醒。`,
				};
			}
		}
	});
}
