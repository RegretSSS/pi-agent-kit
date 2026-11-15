#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "tasks.ts"
    if not path.exists():
        print("task_id_claim_atomic: extensions/tasks.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    nid = re.search(r"async nextId\(\).{0,700}?\n\t\}", source, re.DOTALL)
    if not nid:
        violations.append("缺 nextId——id 分配逻辑没有集中实现")
    else:
        body = nid.group(0)
        if not re.search(r'\.claim`\),\s*"wx"', body):
            violations.append("nextId 缺 O_EXCL claim 原子占位——查重集合只看本地内存,跨进程同毫秒并发 task_create 生成同 id:四任务写同一 log、created 覆盖 tasks.set、children map 覆盖,观测链断裂(11-15 循环审查 P0 实证:199 条 created 卷入 23 条,6 组碰撞)")
        if not re.search(r"claimSuffix\(\)", body):
            violations.append("nextId 缺随机后缀——stamp+seq 相同时纯靠 claim 冲突重试,后缀把冲突概率压到忽略量级")
    if not re.search(r'TASK_ID_SHAPE = /^\\d\{14\}-\\d\+\(\\?\[:-\]\[a-z0-9\]\{1,8\}\)\?\$/', source) and "-[a-z0-9]{1,8}" not in source:
        violations.append("TASK_ID_SHAPE 未放行带后缀 id——新 id 被 journalEventPlausible 拒收,task_create 直接坏")
    if not re.search(r"child\.exitCode !== null \|\| child\.signalCode !== null", source):
        violations.append("watchChild 挂 listener 前缺 exitCode/signalCode 预检——recordCreate(多个 fs await)之后才挂 listener,子进程快速退出时 exit 事件发给零监听者被丢,且 reap 被 skipIds 跳过,任务本会话内永远 running(循环审查 r3 P1:噪声下 47% 命中);ChildProcess 的 exitCode/signalCode 属性在无监听者时仍被赋值,预检即闭合")
    if violations:
        print(f"task_id_claim_atomic: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("task_id_claim_atomic: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
