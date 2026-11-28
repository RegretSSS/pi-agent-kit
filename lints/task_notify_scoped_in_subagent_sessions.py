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
        print("task_notify_scoped_in_subagent_sessions: extensions/tasks.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    if "const SUBAGENT_SESSION_NAME = /#[0-9a-f]{8}$/;" not in source:
        violations.append("子代理会话判别规则变了——pi-subagents 给每个子会话起名 <类型>#<agent id 前 8 位十六进制>,改规则须同时重验 lints/tasks_notify_subagent_real_session.py")
    sweep = block(source, r"\n\tasync function sweep\(\): Promise<void> \{")
    branch = re.search(r"await settleOwnExits\(\);\s*if \(subagentSession\) return;\s*await reapUnownedAndReport\(\);", sweep)
    if branch is None:
        violations.append("sweep 必须先按 subagentSession 分流:子代理会话只结算自己创建的任务并 return,不得走到 reapUnownedAndReport")
    if len(re.findall(r"await reapUnownedAndReport\(\)", source)) != 1 or "async function reapUnownedAndReport()" not in source:
        violations.append("reapUnownedAndReport 只应在 sweep 分流后被调用一处——别处调用会把回收/孤儿告警带进子代理会话")
    settling = block(source, r"\nfunction settleOwnExits\(\): Promise<TaskRecord\[\]> \{")
    if "reportOwnExits(finished)" not in settling:
        violations.append("settleOwnExits 结算后没有通报——结算与通报分家时,bg_* 工具抢先结算会把完成通知吞掉(2026-11-29 实测;行为由 lints/tasks_notify_not_swallowed_by_bg_query.py 守)")
    session_start = block(source, r'pi\.on\("session_start",')
    classify = session_start.find("subagentSession = isSubagentSessionName(ctx.sessionManager?.getSessionName?.());")
    first_maintenance = min((session_start.find(token) for token in ("reapDeadPids(", "sweepOrphanClaims(", "gcExpired(") if token in session_start), default=-1)
    if classify < 0 or (first_maintenance >= 0 and classify > first_maintenance):
        violations.append("session_start 必须先判定 subagentSession,再做任何回收/孤儿清理")
    guarded = re.search(r"if \(!subagentSession\) \{[^}]*reapDeadPids\([^}]*sweepOrphanClaims\(\)[^}]*gcExpired\(\)[^}]*\}", session_start, re.DOTALL)
    if guarded is None:
        violations.append("session_start 的 reapDeadPids / sweepOrphanClaims / gcExpired 必须整体包在 if (!subagentSession) 里")
    if violations:
        print(f"task_notify_scoped_in_subagent_sessions: {len(violations)} 处违规")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print("task_notify_scoped_in_subagent_sessions: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
