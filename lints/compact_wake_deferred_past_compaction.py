#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "compact-tool.ts"
    if not path.exists():
        print("compact_wake_deferred_past_compaction: extensions/compact-tool.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    handler = re.search(r'pi\.on\("session_compact".{0,900}?\n\t\}\);', source, re.DOTALL)
    if not handler:
        violations.append("缺 session_compact handler——无从检查投递时机")
    else:
        body = handler.group(0)
        timer = re.search(r"setTimeout\(", body)
        send = re.search(r"sendUserMessage\(", body)
        if not timer:
            violations.append("唤醒未做宏任务延迟——session_compact 在 compaction 窗口内发射(pi 源码:emit 先于 _clearManualCompactionState),此时 prompt() 无条件 throw \"Cannot submit a prompt while compaction is in progress\",deliverAs:steer 也救不了(throw 在 isStreaming 分支之前),bind 层 .catch 送错误面板即静默——D22 真根因,steer 修复对 manual 路径无效的教训")
        elif not send or send.start() < timer.start():
            violations.append("sendUserMessage 不在 setTimeout 回调内——必须在宏任务里投递,emit 返回后的同步尾巴必已清 controller(run-to-completion 保证)")
        else:
            delay = re.search(r"setTimeout\([^;]*?,\s*(\d+)\s*\)", body, re.DOTALL)
            if delay and delay.group(1) != "0":
                violations.append(f"setTimeout 延迟非 0({delay.group(1)}ms)——这是投递时机问题不是重试退避,宏任务边界即可,长延迟属于 no-long-sleep 域")
    if violations:
        print(f"compact_wake_deferred_past_compaction: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("compact_wake_deferred_past_compaction: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
