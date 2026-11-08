#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "memory.ts"
    if not path.exists():
        print("memory_recall_dedupe: extensions/memory.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    recall_sig = re.search(r"async recall\(([^)]*)\)", source)
    if not recall_sig:
        violations.append("缺少 ScopedMemory.recall——自动召回通道不存在")
    else:
        if "excludeKeys" not in recall_sig.group(1):
            violations.append("recall 签名缺 excludeKeys 参数——同会话重复注入无法避免")
        if not re.search(r"excludeKeys\.has\(", source):
            violations.append("recall 过滤未查 excludeKeys——已注入条目会二次出现(用户约束:上下文中不出现第二次)")
    handler = re.search(r'pi\.on\("before_agent_start".{0,2600}?\n\t\}\);', source, re.DOTALL)
    if not handler:
        violations.append("缺少 before_agent_start 注入 handler")
    else:
        body = handler.group(0)
        if 'event.messageType !== "user"' not in body:
            violations.append("recall 未限定 messageType===\"user\"——subagent/custom 消息触发的 run 会重复召回且与其任务无关")
        if "recalledKeys.add" not in body:
            violations.append("注入前未把命中键记入 recalledKeys——去重集永不增长")
        add_at = body.find("recalledKeys.add")
        message_at = body.find("customType")
        if add_at < 0 or message_at < 0 or add_at > message_at:
            violations.append("recalledKeys.add 必须先于 message 注入返回——注入失败重试时才不会漏记")
        if 'customType: "agent-memory-recall"' not in body:
            violations.append("注入消息缺 customType: \"agent-memory-recall\"——无法在 transcript/过滤层识别召回通道")
        if "display: false" not in body:
            violations.append("注入消息缺 display: false——自动召回是给 LLM 的上下文,TUI 刷屏会干扰用户")
    if violations:
        print(f"memory_recall_dedupe: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("memory_recall_dedupe: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
