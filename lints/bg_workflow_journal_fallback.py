#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def block(source: str, start_pattern: str) -> str:
    match = re.search(start_pattern, source)
    if match is None:
        return ""
    depth = 0
    for index in range(match.start(), len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    return source[match.start() :]


def main() -> int:
    path = ROOT / "extensions" / "tasks.ts"
    if not path.exists():
        print("bg_workflow_journal_fallback: extensions/tasks.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    for tool, needle in (("bg_status", "journalFallbackStatus("), ("bg_log", "workflowJournalTail(")):
        tool_block = block(source, rf'pi\.registerTool\(\{{\s*\n\s*name: "{tool}"')
        if not tool_block:
            violations.append(f"缺 {tool} 工具")
        elif needle not in tool_block:
            violations.append(f"{tool} 对 wf 无 journal 降级——RPC patch 未同步/超时即全盲(11-15 aicontest 工单③),只读 journal tail 是 patch 前的最小可观测面")
    if not re.search(r"if \(!RUN_ID_SHAPE\.test\(runId\)\) return null;", source):
        violations.append("journal 降级缺 runId 白名单校验——readdir/readFile 拼 ../../ 路径即任意文件读取")
    if not re.search(r'if \(typeof entry\.index !== "number" \|\| typeof entry\.ok !== "boolean"\) continue;', source):
        violations.append("journal 收行条件变了——不能以 text 存在为条件:上游 ok:false 条目从不带 text,否则失败条目全部被丢,跑飞的 run 在降级视图里显示为全部成功(审查#1)")
    listing = block(source, r"async function listWorkflowRuns")
    if ".workflow.jsonl" not in listing:
        violations.append("workflow 清单无 journal 降级——RPC 挂时连有哪些 run 都不可见")
    if violations:
        print(f"bg_workflow_journal_fallback: {len(violations)} 处违规")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print("bg_workflow_journal_fallback: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
