#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

MEMORY_DIR = Path(os.environ.get("AGENTS_MEMORY_DIR", Path.home() / ".agents" / "memory"))
INDEX_LINE = re.compile(r"^- \[[^\]]+\]\(([^)]+\.md)\)")
FRONTMATTER_NAME = re.compile(r"^name:\s*(\S+)")


def indexed_files(index_text: str) -> set[str]:
    return {m.group(1) for m in INDEX_LINE.finditer(index_text)}


def memory_files(memory_dir: Path) -> set[str]:
    return {p.name for p in memory_dir.glob("*.md") if p.name != "MEMORY.md"}


def lint(memory_dir: Path | None = None) -> list[str]:
    memory_dir = memory_dir or MEMORY_DIR
    if not memory_dir.is_dir():
        return []
    problems = []
    index_path = memory_dir / "MEMORY.md"
    index_text = index_path.read_text() if index_path.exists() else ""
    indexed = indexed_files(index_text)
    on_disk = memory_files(memory_dir)
    for missing in sorted(indexed - on_disk):
        problems.append(f"agentsmd_index_consistency: MEMORY.md 索引指向不存在的文件 {missing}")
    for unindexed in sorted(on_disk - indexed):
        problems.append(f"agentsmd_index_consistency: memory 文件缺索引行 {unindexed}")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    print("agentsmd_index_consistency: ok" if not found else "")
    sys.exit(1 if found else 0)
