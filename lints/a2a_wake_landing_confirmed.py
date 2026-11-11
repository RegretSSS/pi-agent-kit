#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "a2a-inbox.ts"
    if not path.exists():
        print("a2a_wake_landing_confirmed: extensions/a2a-inbox.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    submit = re.search(r"pi\.sendUserMessage\(", source)
    precheck = re.search(r"if \(wakeLanded\(marker\)\) \{", source)
    confirm = re.search(r"setTimeout\(\(\) => \{.{0,200}?wakeLanded\(marker\)", source, re.DOTALL)
    if not re.search(r"const LANDING_MAX_ATTEMPTS = \d+;", source):
        violations.append("缺 LANDING_MAX_ATTEMPTS 上限——落地确认失败会无限重试")
    if not precheck or not submit or precheck.start() > submit.start():
        violations.append("sendUserMessage 前缺 wakeLanded 预检——上次已落地但确认窗口错过的信会在重试时二次注入")
    if not confirm or (submit and confirm.start() < submit.start()):
        violations.append("缺 setTimeout+wakeLanded 落地确认——pi.sendUserMessage 是 bind 层吞错的 fire-and-forget,compaction 窗口/无模型等 prompt() throw 全被 .catch 送错误面板,rcpt 照写即丢信(D22 同族,a2a 版)。必须确认 branch 里真出现 user 消息才 markDelivered,否则留 inflight 退场由 rescuer 重试")
    if re.search(r"markDelivered\(\);", source):
        violations.append("markDelivered 残留无参调用——签名已带 (msgId, rcpt)")
    if violations:
        print(f"a2a_wake_landing_confirmed: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("a2a_wake_landing_confirmed: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
