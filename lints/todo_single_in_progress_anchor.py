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
    if "appendEntry" not in source or "TODO_STATE_ENTRY" not in source:
        violations.append("状态变更未走 appendEntry(todo-state) 持久化——jsonl 的 toolResult 不落盘 details(实测七键无 details),不落 custom entry 则重启即失忆(D21 审查定谳:文本协议是膏药根因)")
    commit_block = re.search(r"const commit = \(action.{0,500}?\n\t+\};", source, re.DOTALL)
    if not commit_block:
        violations.append("缺 commit 集中提交点——appendEntry 应统一在变更出口,散落各分支必有遗漏(clear 空态尤其要落,否则重启复活)")
    else:
        changes = re.findall(r'return commit\(', source)
        if len(changes) < 4:
            violations.append(f"变更动作(add/status/toggle/clear)只有 {len(changes)} 个走 commit——全部四动作必须落盘")
    if "settleDone" not in source or "DONE_KEEP" not in source:
        violations.append("缺 done 沉降(DONE_KEEP/settleDone)——已完条目无界累积会冲爆上下文(每次工具 content 全量渲染)")
    if "nextId" not in source:
        violations.append("缺 nextId 传递——重建后新增条目会撞 id")
    if re.search(r"parseTodos|contentText", source):
        violations.append("残留 content 文本逆解析——已被 custom entry 正解取代,双协议并存是未清理干净的膏药")
    if violations:
        print(f"todo_single_in_progress_anchor: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("todo_single_in_progress_anchor: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
