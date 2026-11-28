import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SLEEP_LIMIT_SECONDS = 100;

const SUFFIX_SECONDS: Record<string, number> = { "": 1, s: 1, m: 60, h: 3600, d: 86400 };

const FOREVER = new Set(["inf", "infinity"]);

const SLEEP_WORD = /\bsleep/g;

const SLEEP_DURATION = /\s+([+]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|inf(?:inity)?))([smhd]?)(?![\w.])/y;

let matchedDurations = "";

function durationSeconds(value: string): number {
	return FOREVER.has(value) ? Infinity : Number(value);
}

function invocationSeconds(command: string, start: number): number {
	let seconds = 0;
	matchedDurations = "";
	SLEEP_DURATION.lastIndex = start;
	for (let match = SLEEP_DURATION.exec(command); match; match = SLEEP_DURATION.exec(command)) {
		seconds += durationSeconds(match[1]) * SUFFIX_SECONDS[match[2]];
		matchedDurations = matchedDurations ? `${matchedDurations} ${match[0].trim()}` : match[0].trim();
	}
	return seconds;
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", (event) => {
		if (event.toolName !== "bash") return;
		const command = (event.input as { command?: string })?.command;
		if (typeof command !== "string") return;
		SLEEP_WORD.lastIndex = 0;
		let word: RegExpExecArray | null;
		while ((word = SLEEP_WORD.exec(command)) !== null) {
			const seconds = invocationSeconds(command, word.index + word[0].length);
			if (seconds > SLEEP_LIMIT_SECONDS) {
				const lasted = seconds === Infinity ? "永不返回" : `${seconds}s`;
				return {
					block: true,
					reason: `裸 sleep ${matchedDurations}（${lasted}）超过 ${SLEEP_LIMIT_SECONDS}s 上限，禁止阻塞会话。等待请用 task_create 后台任务或定时任务，到点自动唤醒。`,
				};
			}
		}
	});
}
