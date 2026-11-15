#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "tasks.ts"
    if not path.exists():
        print("task_notify_deferred_during_compaction: extensions/tasks.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    deliver = re.search(r"function deliverNotify\(content: string\): void \{(.{0,300}?)\n\t\}", source, re.DOTALL)
    if not deliver:
        violations.append("缺 deliverNotify 守卫出口——task-notify 的 sendCustomMessage(triggerTurn) 在 pi 核心走 _startRun 无 compaction 守卫(prompt() 有,sendCustomMessage 没有),compaction 摘要进行中注入会起新 run 与摘要落地改树打架,compact 被打断成半完成态(11-15 aicontest 实报)")
    else:
        body = deliver.group(1)
        if "sessionIdle" not in body or "pendingNotify" not in body:
            violations.append("deliverNotify 未检查 sessionIdle/未入 pendingNotify 队列——ctx.isIdle() 实现为 !runActive && !isCompacting,是扩展层唯一可探测 compaction 窗口的接口")
    if not re.search(r"pendingNotify\.length > 0 && \(!sessionIdle \|\| sessionIdle\(\)\)", source):
        violations.append("sweep 缺 pendingNotify 冲洗分支——compaction 结束后积压通知永不投递")
    if re.search(r"pi\.sendMessage\(\s*\{ customType: \"task-notify\"", source) and len(re.findall(r'customType: "task-notify"', source)) > 2:
        violations.append("task-notify 直连 sendMessage 多于冲洗分支一处——绕过 deliverNotify 的注入点会复发竞态")
    if violations:
        print(f"task_notify_deferred_during_compaction: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("task_notify_deferred_during_compaction: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
