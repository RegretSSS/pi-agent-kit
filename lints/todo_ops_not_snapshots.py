#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def violations(source: str) -> list[str]:
    found = []
    writes = re.findall(r"appendEntry\(\s*([A-Z_]+|\"[^\"]+\")", source)
    if not writes:
        found.append("没有任何 appendEntry 写入——状态不落盘,重启即失忆")
    for name in writes:
        if name != "TODO_OP_ENTRY":
            found.append(f"appendEntry 写的是 {name} 而不是逐操作增量 TODO_OP_ENTRY——每次操作整表重写:一个连用 22 天的会话 1591 次写入占了 280MB,占该文件 62%")
    replay = re.search(r"export function reconstructTodos\(.*?\n\}", source, re.DOTALL)
    if not replay or "LEGACY_SNAPSHOT_ENTRY" not in replay.group(0):
        found.append("reconstructTodos 不再识别旧的全量快照条目(LEGACY_SNAPSHOT_ENTRY)——升级前写的会话重启后清单清零")
    if not replay or "TODO_OP_ENTRY" not in replay.group(0):
        found.append("reconstructTodos 不回放增量条目(TODO_OP_ENTRY)——写了不读,重启即失忆")
    if not re.search(r"\{ \.\.\.op, settled: ", source):
        found.append("沉降没有并进触发它的那条操作——加条目与沉降分成两条,中途崩溃会留下加了却没沉降的半截状态")
    commit = re.search(r"const commit = \(action.*?\n\t+\};", source, re.DOTALL)
    if not commit:
        found.append("缺 commit 集中提交点——appendEntry 应统一在变更出口")
    else:
        written = commit.group(0).find("pi.appendEntry(")
        applied = commit.group(0).find("state = applyOp(")
        if written < 0 or applied < 0 or applied < written:
            found.append("内存状态先于落盘更新——写失败时内存领先文件:整表快照时下一次写入能自愈,增量落盘下没落盘的改动会永久丢失")
    return found


def lint(repo: Path) -> list[str]:
    path = repo / "extensions" / "todo.ts"
    if not path.exists():
        return ["extensions/todo.ts 不存在"]
    return violations(path.read_text(errors="ignore"))


def main() -> int:
    found = lint(ROOT)
    for item in found:
        print(f"todo_ops_not_snapshots: {item}")
    if found:
        return 1
    print("todo_ops_not_snapshots: ok(状态逐操作增量落盘,旧快照可读,写成功才更新内存)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
