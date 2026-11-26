#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_LOOP_CANDIDATES = (
    Path.home() / ".local/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core/dist/agent-loop.js",
    Path.home() / ".local/lib/node_modules/@earendil-works/pi-agent-core/dist/agent-loop.js",
)


def between(source: str, start: str, end: str) -> str:
    match = re.search(re.escape(start) + r"(.*?)" + re.escape(end), source, re.DOTALL)
    return match.group(1) if match else ""


def pi_order_problems() -> tuple[list[str], bool]:
    path = next((candidate for candidate in AGENT_LOOP_CANDIDATES if candidate.exists()), None)
    if path is None:
        return [], False
    source = path.read_text(errors="ignore")
    problems = []
    for name, end in (("executeToolCallsSequential", "async function executeToolCallsParallel("), ("executeToolCallsParallel", "function shouldTerminateToolBatch(")):
        body = between(source, f"async function {name}(", end)
        start_at = body.find('type: "tool_execution_start"')
        before_at = body.find("prepareToolCall(")
        hook_at = body.find("finalizeExecutedToolCall(")
        end_at = body.find("emitToolExecutionEnd(", hook_at)
        if min(start_at, before_at, hook_at, end_at) < 0:
            problems.append(f"pi 的 {name} 结构已变,无法核对事件顺序——必须重新核实 pi 的事件发射顺序再改 pi-guard")
        elif not start_at < before_at or not hook_at < end_at:
            problems.append(f"pi 的 {name} 事件顺序已变(tool_execution_start={start_at} tool_call={before_at} tool_result={hook_at} tool_execution_end={end_at})——pi-guard 的跟踪入口必须随之调整")
    return problems, True


def lint() -> list[str]:
    problems = []
    source = (ROOT / "extensions" / "pi-guard.ts").read_text()
    if 'pi.on("tool_execution_start"' in source:
        problems.append("pi-guard 不得依赖 tool_execution_start——pi 先发 tool_execution_start 再发 tool_call,此时命令尚未改写、跟踪尚未建立")
    entry = re.search(r'pi\.on\("tool_call", \(event, ctx\) => \{\n\t*if \(event\.toolName === "bash"\) this\.begin\(event\.toolCallId, event\.input, ctx', source)
    if entry is None:
        problems.append("跟踪必须在 tool_call 钩子里建立(this.begin(event.toolCallId, event.input, ctx))——改写命令与登记跟踪必须同处一个钩子")
    driver = (ROOT / "tests" / "pi_guard_driver.mjs").read_text()
    start_at = driver.find("await handlers.tool_execution_start?.(")
    call_at = driver.find("await handlers.tool_call?.(")
    if min(start_at, call_at) < 0 or start_at > call_at:
        problems.append("驱动必须按 pi 的真实顺序发事件:tool_execution_start 先于 tool_call——驱动顺序错了会把错误的事件假设固化进测试")
    return problems


if __name__ == "__main__":
    found = lint()
    pi_found, checked = pi_order_problems()
    found.extend(pi_found)
    for item in found:
        print(f"pi_guard_tool_call_order: {item}")
    if not checked:
        print("pi_guard_tool_call_order: 未找到已安装的 pi,跳过 pi 事件顺序核对")
    print("pi_guard_tool_call_order: ok" if not found else "")
    sys.exit(1 if found else 0)
