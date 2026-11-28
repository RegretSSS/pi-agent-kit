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
        violations.append("缺 deliverNotify 守卫出口——task-notify 的 sendCustomMessage(triggerTurn) 在 pi 核心走 _startRun 无 compaction 守卫,会把进行中的 compact 打断成半完成态")
    else:
        body = deliver.group(1)
        if "inMaintenance()" not in body or "pendingNotify" not in body:
            violations.append("deliverNotify 未经 inMaintenance() 守卫或未入 pendingNotify 队列——压缩窗口内注入会打断 compact")
        if "sessionIdle" in body:
            violations.append("deliverNotify 直接看 sessionIdle()——不空闲≠在压缩;回合进行中也扣留会让模型等不到通知而连环轮询(2026-11-15~28 实证)")
    guard = re.search(r"function inMaintenance\(\): boolean \{\s*return ([^\n]+)\n", source)
    if guard is None:
        violations.append("缺 inMaintenance() 判定")
    elif not ("!sessionIdle()" in guard.group(1) and "!agentRunning" in guard.group(1)):
        violations.append("inMaintenance() 必须同时要求「不空闲」与「无 agent 回合在跑」——只看前者即回到整回合扣留")
    if not re.search(r"pi\.on\(\"agent_start\",[^\n]*\n\s*agentRunning = true;", source) or not re.search(r"pi\.on\(\"agent_end\",[^\n]*\n\s*agentRunning = false;", source):
        violations.append("agentRunning 须由 agent_start / agent_end 事件维护——回合结束到核心置空闲之间不能把通知 steer 进已收尾的循环")
    if not re.search(r"pendingNotify\.length > 0 && !inMaintenance\(\)", source):
        violations.append("sweep 缺 pendingNotify 冲洗分支——维护窗口结束后积压通知永不投递")
    if len(re.findall(r'customType: "task-notify"', source)) > 2:
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
