#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[bp]-[A-Za-z0-9-]{20,}"),
    re.compile(r"zai[-_][A-Za-z0-9_-]{12,}"),
    re.compile(r"\b[0-9a-f]{32}\.[A-Za-z0-9]{12,}\b"),
)
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
SELF = Path(__file__).resolve().name


def lint(root: Path | None = None) -> list[str]:
    root = root or ROOT
    problems = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.parent.name == "lints" and path.name == SELF:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16", errors="ignore")
        else:
            text = raw.decode("utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            hit = pattern.search(text)
            if hit:
                rel = path.relative_to(root)
                problems.append(
                    f"no_secrets: {rel} 疑似凭据形态 {hit.group(0)[:12]}… —— 移除或改环境变量引用后再提交"
                )
                break
    return problems


if __name__ == "__main__":
    found = lint(Path(os.environ.get("LINT_ROOT", ROOT)))
    for item in found:
        print(item)
    print("no_secrets: ok" if not found else "")
    sys.exit(1 if found else 0)
