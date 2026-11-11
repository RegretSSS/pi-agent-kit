#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "todo.ts"
    if not path.exists():
        print("todo_single_in_progress_anchor: extensions/todo.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    mark = re.search(r"export function markStatus\([^)]*\)[^{]*\{(.{0,900}?)\n\}", source, re.DOTALL)
    if not mark:
        violations.append("缺 markStatus 导出——in_progress 单锚点语义没有集中实现")
    else:
        body = mark.group(1)
        if not re.search(r'status\s*===\s*"in_progress"', body):
            violations.append("markStatus 未识别 in_progress——三态不完整")
        if not re.search(r't\.status\s*=\s*"pending"', body) and not re.search(r'status:\s*"pending"', body):
            violations.append("in_progress 设置时未把其他进行中项退回 pending——多锚点并存会让模型失焦(CC TodoWrite 单锚点语义)")
    if not re.search(r'pi\.on\("session_start".{0,200}?rebuild', source, re.DOTALL) or not re.search(r'pi\.on\("session_tree".{0,200}?rebuild', source, re.DOTALL):
        violations.append("session_start/session_tree 未双挂 rebuild——branch/恢复后清单状态不回放,分支感知设计落空")
    if "toolName !== \"todo\"" not in source.replace("!", "!"):
        pass
    if not re.search(r'toolName\s*!==\s*"todo"', source):
        violations.append("reconstruct 未过滤 toolName===\"todo\" 的 toolResult——重放会吃到别的工具的 details")
    if "nextId" not in source:
        violations.append("缺 nextId 传递——重建后新增条目会撞 id")
    if violations:
        print(f"todo_single_in_progress_anchor: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("todo_single_in_progress_anchor: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
