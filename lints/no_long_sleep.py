#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOBAL_REGEX = re.compile(r"^\s*const\s+(\w+)\s*=\s*/.*/[a-z]*g[a-z]*\s*;", re.MULTILINE)


def lint(root: Path | None = None) -> list[str]:
    path = (root or ROOT) / "extensions" / "no-long-sleep.ts"
    if not path.exists():
        return ["extensions/no-long-sleep.ts 不存在——用户令(会话内禁止 sleep 超过 100 秒阻塞自身)需要机械面,仅靠提示词是软约束"]
    source = path.read_text(errors="ignore")
    problems = []
    if not re.search(r'pi\.on\("tool_call"', source):
        problems.append("缺 tool_call 拦截注册——bash 工具是同步阻塞的,长 sleep 只有在调用前拦下才有意义")
    if not re.search(r'event\.toolName !== "bash"', source):
        problems.append("未限定 toolName==bash——对非 bash 工具误拦会阻断无关调用")
    if "SLEEP_LIMIT_SECONDS" not in source or not re.search(r">\s*SLEEP_LIMIT_SECONDS\b", source):
        problems.append("阈值判定没有走 SLEEP_LIMIT_SECONDS——上限散落在字面量里,改用户令时漏改一处就出现两个上限")
    for name in GLOBAL_REGEX.findall(source):
        if f"{name}.lastIndex = 0" not in source:
            problems.append(f"带 g 标志的正则 {name} 没有在每次使用前重置 lastIndex——上一条命令被拦时 exec 停在中途,下一条命令从残留位置开始扫,开头的长 sleep 漏拦")
    if "task_create" not in source or "block: true" not in source:
        problems.append("block reason 缺 task_create 引导——拦截必须给出替代路径,否则模型只能原地重试")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(f"no_long_sleep: {item}")
    print("no_long_sleep: ok" if not found else "")
    sys.exit(1 if found else 0)
