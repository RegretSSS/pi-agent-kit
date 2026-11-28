import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BLOCK_REASON =
	"后台化命令被拦截（用户令：不允许后台运行完成不通报的 task）。长任务请改用 task_create——退出即通知会话并附尾部日志；跟踪用 bg_list / bg_status，读输出用 bg_log。";

const COMMAND_POSITION_BACKGROUND =
	/(?:^|[;&|(`\n]\s*)(?:env\s+[A-Za-z_][A-Za-z0-9_]*=\S*\s+)?(?:nohup|setsid|disown)\b/;

function endsWithBackgroundAmp(command: string): boolean {
	const trimmed = command.trimEnd();
	if (trimmed.length < 2) return false;
	if (!trimmed.endsWith("&")) return false;
	if (trimmed[trimmed.length - 2] === "&") return false;
	return true;
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", (event) => {
		if (event.toolName !== "bash") return;
		const command = (event.input as { command?: string })?.command;
		if (typeof command !== "string") return;
		if (COMMAND_POSITION_BACKGROUND.test(command) || endsWithBackgroundAmp(command)) {
			return { block: true, reason: BLOCK_REASON };
		}
	});
}
