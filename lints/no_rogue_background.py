#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "no-rogue-background.ts"
    if not path.exists():
        print("no_rogue_background: extensions/no-rogue-background.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    if not re.search(r'pi\.on\("tool_call"', source):
        violations.append("缺 tool_call 拦截注册——用户令(不允许后台运行完成不通报的 task)需要机械面,仅靠提示词是软约束")
    if not re.search(r'event\.toolName !== "bash"', source):
        violations.append("未限定 toolName==bash——对非 bash 工具误拦会阻断无关调用")
    for word in ("nohup", "setsid", "disown"):
        if not re.search(rf"\b{word}\b", source):
            violations.append(f"模式清单缺 {word}——工单点名的后台化路径(11-16 aicontest nohup 裸起两次)")
    regex_assign = re.search(r"COMMAND_POSITION_BACKGROUND\s*=\s*/(.*)/[a-z]*;", source)
    if not regex_assign:
        violations.append("缺命令位正则——裸 \bword\b 匹配会把 grep nohup file 这类读操作误拦")
    elif regex_assign.group(0).endswith("/g;"):
        violations.append("命令位正则带 g 标志——带 g 的 .test 有 lastIndex 状态,同一命令多次判定结果漂移")
    if "endsWithBackgroundAmp" not in source:
        violations.append("缺结尾 & 检测——nohup 之外的裸 & 后台化是工单第二形态")
    if not re.search(r"endsWithBackgroundAmp\(command\)", source):
        violations.append("endsWithBackgroundAmp 定义后未接入 tool_call 判定路径——死代码检查永不触发")
    if "task_create" not in source or "block: true" not in source:
        violations.append("block reason 缺 task_create 引导——拦截必须给出替代路径,否则模型只能原地重试")
    if violations:
        print(f"no_rogue_background: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("no_rogue_background: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
