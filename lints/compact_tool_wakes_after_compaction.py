#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "compact-tool.ts"
    if not path.exists():
        print("compact_tool_wakes_after_compaction: extensions/compact-tool.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    handler = re.search(r'pi\.on\("session_compact".{0,600}?\n\t\}\);', source, re.DOTALL)
    if not handler:
        violations.append("缺 session_compact 唤醒 handler——compact 吃掉工作状态后模型失忆,无人拉回")
    else:
        body = handler.group(0)
        if "willRetry" not in body:
            violations.append("未判 willRetry——overflow 恢复中注入用户消息会混进重试 run,污染重试输入")
        if re.search(r"sendUserMessage\([^;]*?\)\s*\.(?:then|catch|finally)\b", body, re.DOTALL):
            violations.append("sendUserMessage 被链式调用——ExtensionAPI 层 fire-and-forget 返回 undefined,.then 即 TypeError(D16 三坑之一)")
        if re.search(r"await\s+pi\.sendUserMessage", body):
            violations.append("await sendUserMessage——返回 undefined 的假承诺,直调即可")
        if "fold-index" not in body:
            violations.append("唤醒词缺 fold-index 重定位指引——醒来第一件事应按摘要索引恢复状态而非重新摸索")
    if not re.search(r"sendUserMessage", source) and handler:
        violations.append("handler 未调用 sendUserMessage——唤醒词无注入通道")
    if violations:
        print(f"compact_tool_wakes_after_compaction: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("compact_tool_wakes_after_compaction: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
