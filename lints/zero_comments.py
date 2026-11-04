#!/usr/bin/env python3
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
TS_COMMENT = re.compile(r"(?<!:)//")
TS_BLOCK_OPEN = re.compile(r"/\*(?!/)")


def python_violations(path: Path) -> list[str]:
    found = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type == tokenize.COMMENT and token.start[0] > 1:
                found.append(f"{path}:{token.start[0]}: {token.string}")
    return found


def line_comment_violations(path: Path, marker: re.Pattern[str]) -> list[str]:
    found = []
    in_block = False
    for number, line in enumerate(path.read_text(errors="ignore").splitlines(), start=1):
        stripped = line.strip()
        if in_block:
            found.append(f"{path}:{number}: {stripped}")
            if "*/" in stripped:
                in_block = False
            continue
        if stripped.startswith("#") and number != 1:
            found.append(f"{path}:{number}: {stripped}")
            continue
        if stripped.startswith("/*"):
            found.append(f"{path}:{number}: {stripped}")
            if "*/" not in stripped:
                in_block = True
            continue
        if path.suffix in {".ts", ".mts"} and marker.search(line.rstrip()):
            found.append(f"{path}:{number}: {line.strip()}")
    return found


def lint(root: Path | None = None) -> list[str]:
    root = root or ROOT
    violations = []
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix == ".py":
            violations.extend(python_violations(path))
        elif path.suffix in {".sh", ".ts", ".mts"}:
            violations.extend(line_comment_violations(path, TS_COMMENT))
    return violations


if __name__ == "__main__":
    found = lint()
    for line in found:
        print(line)
    if found:
        print(f"zero_comments: {len(found)} 处注释违规(想写注释 = 命名不够好,去改名)")
        sys.exit(1)
    print("zero_comments: ok")
    sys.exit(0)
