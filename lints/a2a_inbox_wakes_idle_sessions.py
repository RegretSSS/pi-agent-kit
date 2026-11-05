#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "a2a-inbox.ts"
    if not path.exists():
        print("a2a_inbox_wakes_idle_sessions: extensions/a2a-inbox.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    if re.search(r"sendUserMessage", source):
        violations.append("使用 sendUserMessage——空闲会话只入 followUp 队列不启动回合(消息被冷藏),必须 sendMessage + triggerTurn:true")
    if not re.search(r"triggerTurn:\s*true", source):
        violations.append("缺少 triggerTurn: true——空闲会话不会被唤醒")
    for violation in violations:
        print(f"a2a_inbox_wakes_idle_sessions: {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
