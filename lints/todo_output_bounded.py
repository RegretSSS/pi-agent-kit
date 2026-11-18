#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "todo.ts"
    if not path.exists():
        print("todo_output_bounded: extensions/todo.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    if "TODO_LIST_KEEP" not in source or not re.search(r"cap: number = TODO_LIST_KEEP", source):
        violations.append("list 输出无行数上限——529 pending 挂账时每次刷 500+ 行烧上下文(11-18 aicontest 工单)")
    if not re.search(r't\.status !== "pending"', source) or "slice(0, cap)" not in source:
        violations.append("截断未把非 pending 前置——in_progress 锚点会被淹没在挂账堆里截掉")
    if "另有" not in source or "todo full" not in source or "todo archive" not in source:
        violations.append("截断缺逃逸口提示——被截时模型必须知道 full/archive 两条出路")
    enum_match = re.search(r'StringEnum\(\[(.*?)\] as const\)', source)
    if not enum_match or '"archive"' not in enum_match.group(1) or '"full"' not in enum_match.group(1):
        violations.append("动作集缺 archive/full——pending 挂账无机械清账面,永不沉降(工单表现1)")
    status_block = re.search(r'case "status":(.*?)case "toggle":', source, re.DOTALL)
    toggle_block = re.search(r'case "toggle":(.*?)case "archive":', source, re.DOTALL)
    for name, block in (("status", status_block), ("toggle", toggle_block)):
        if block and "formatTodos" in block.group(1):
            violations.append(f'{name} 回执返回全表 formatTodos——每次状态变更刷全量行(工单表现1噪音源)')
    if re.search(r"details: \{ action, todos", source) or re.search(r"todos: \[\.\.\.todos\]", source) or re.search(r"type TodoDetails = [^=]*todos", source):
        violations.append("details 仍携带全量 todos 数组——tool result 落盘成第二膨胀源(该会话 16.3MB 实证)")
    if "是进行中锚点" not in source:
        violations.append("archive 不保护 in_progress 锚点——批量归档会把活动锚点一起清掉,单锚点纪律失守")
    if violations:
        print(f"todo_output_bounded: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("todo_output_bounded: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
