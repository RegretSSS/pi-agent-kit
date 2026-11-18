#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "a2a-inbox.ts"
    if not path.exists():
        print("a2a_inject_idempotent: extensions/a2a-inbox.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    if not re.search(r'path\.join\(agentDir\(\), `inj-\$\{msgId\}`\)', source) or not re.search(r'openSync\(claim, "wx"\)', source):
        violations.append("缺 inj- claim O_EXCL 占位——跨进程无闸时多 pi 进程共享同一 agentDir 会各自重注(11-18 事故形态之一)")
    if not re.search(r"fs\.existsSync\(claim\)", source) or not re.search(r"rmSync\(claim, \{ force: true \}\)", source):
        violations.append("claim 缺存在性闸/释放路径——throw 后不释放则该信永久失投")
    if not re.search(r"const CLAIM_STALE_MS = \d+;", source) or not re.search(r"statSync\(claim\)\.mtimeMs < CLAIM_STALE_MS", source):
        violations.append("缺陈旧 claim 回收窗——claim 属主崩溃后无人再注,信件静默丢失")
    throw_release = re.search(r'pi\.sendUserMessage\(wakeText, \{ deliverAs: "steer" \}\);\s*\}\s*catch\s*\{.{0,400}?rmSync\(claim', source, re.DOTALL)
    if not throw_release:
        violations.append("sendUserMessage throw 后未释放 claim——compaction 窗口 throw 一次即永久占位,信件丢失(D22 同族)")
    if re.search(r"const attempts|LANDING_MAX_ATTEMPTS", source):
        violations.append("残留 attempts 计数重注机制——落地检测超时重注=按设计制造重复注入(11-18 事故:74 秒 36 连注,aicontest 会话被打断 7 轮)")
    if re.search(r"attempts\.delete|attempts\.get|attempts\.set", source):
        violations.append("残留 attempts 引用——map 已删,死引用在加载期即 ReferenceError")
    if violations:
        print(f"a2a_inject_idempotent: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("a2a_inject_idempotent: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
