#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "tasks.ts"
    if not path.exists():
        print("task_exit_observable: extensions/tasks.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    if not re.search(r"child\.unref\(\);", source):
        violations.append("spawn 段缺同步 child.unref()——print/json 模式(pi -p)会话完成后靠事件循环排空退出,运行中任务的 child handle 吊住进程整段任务时长;unref 不丢 exit 事件(Node v24 实测,循环审查P1实证),工单①真因是 reap 竞态已另修")
    if not re.search(r'child\.on\("exit",\s*\(code,\s*signal\)', source):
        violations.append("exit handler 未收 signal 参数——被杀任务 code=null 且 signal 丢失,成功/被杀/崩溃三态不可分")
    if not re.search(r"kind: \"orphan\"", source) or "livingForeignTasks" not in source:
        violations.append("缺孤儿检测(orphan 事件/livingForeignTasks)——父进程死后子任务无告警继续跑(11-15 aicontest 工单②)")
    if "exitText" not in source or "unknown(reaped" not in source:
        violations.append("缺 exitText 三态分层——轮询兜底拿不到观测时应明示 unknown 而非与被杀混淆")
    if violations:
        print(f"task_exit_observable: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("task_exit_observable: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
