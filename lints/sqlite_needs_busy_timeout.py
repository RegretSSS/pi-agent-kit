#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_OPEN = re.compile(r"new DatabaseSync\(")


def lint(root: Path | None = None) -> list[str]:
    root = root or ROOT
    problems = []
    for path in sorted((root / "extensions").glob("*.ts")):
        text = path.read_text(errors="ignore")
        for match in DB_OPEN.finditer(text):
            window = text[match.start() : match.start() + 400]
            if "busy_timeout" not in window:
                line = text[: match.start()].count("\n") + 1
                problems.append(
                    f"sqlite_needs_busy_timeout: {path.name}:{line} new DatabaseSync 后未设 busy_timeout——多 pi 会话并发写同一库时 SQLITE_BUSY 直接炸 handler,必须 PRAGMA busy_timeout(+WAL)"
                )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    print("sqlite_needs_busy_timeout: ok" if not found else "")
    sys.exit(1 if found else 0)
