#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path


def porcelain(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def dirty_lines(lines: list[str]) -> list[str]:
    found = []
    for line in lines:
        code = line[:2]
        if code == "??":
            found.append(line)
        elif code[1] != " ":
            found.append(line)
    return found


def lint(repo: Path | None = None) -> list[str]:
    repo = repo or Path(os.environ.get("COMMIT_MUST_CLEAR_REPO", Path(__file__).resolve().parent.parent))
    if not (repo / ".git").exists():
        return []
    dirty = dirty_lines(porcelain(repo))
    if not dirty:
        return []
    preview = "; ".join(dirty[:5])
    return [
        f"commit_must_clear_git_status: 工作树未收干净({len(dirty)} 处未暂存/未跟踪):{preview} —— 收进本次提交或先行处理,不留杂项"
    ]


if __name__ == "__main__":
    problems = lint()
    for item in problems:
        print(item)
    print("commit_must_clear_git_status: ok" if not problems else "")
    sys.exit(1 if problems else 0)
