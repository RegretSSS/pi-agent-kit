#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL_CALL = re.compile(r'\b(?:prepare|exec)\s*\(\s*([\'"])(.*?)\1', re.DOTALL)


def main() -> int:
    path = ROOT / "extensions" / "history.ts"
    if not path.exists():
        print("history_db_select_only: extensions/history.ts 不存在")
        return 1
    violations = []
    for match in SQL_CALL.finditer(path.read_text(errors="ignore")):
        sql = match.group(2).strip()
        head = sql.split(None, 1)[0].upper() if sql else ""
        allowed = head == "SELECT" or sql.upper().startswith("PRAGMA")
        if not allowed:
            violations.append(sql[:80])
    for sql in violations:
        print(f"history_db_select_only: 非只读语句触及 billion-context 库: {sql}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
