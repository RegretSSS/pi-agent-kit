#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL_OVERWRITE = re.compile(r"(rename|writeFile)\([^)]*tasks\.jsonl")
TMP_REWRITE = re.compile(r"tasks\.jsonl[^\n]*\.tmp")


def lint(root: Path | None = None) -> list[str]:
    root = root or ROOT
    problems = []
    for path in sorted((root / "extensions").glob("*.ts")):
        text = path.read_text(errors="ignore")
        for match in JOURNAL_OVERWRITE.finditer(text):
            line = text[: match.start()].count("\n") + 1
            problems.append(
                f"tasks_journal_append_only: {path.name}:{line} 对 tasks.jsonl 使用 {match.group(1)}——覆写式压实与并发 append 竞态会静默丢他窗事件,journal 只许 appendFile(压缩走 gc tombstone 事件)"
            )
        for match in TMP_REWRITE.finditer(text):
            line = text[: match.start()].count("\n") + 1
            problems.append(f"tasks_journal_append_only: {path.name}:{line} 检测到 journal 临时文件重写模式")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    print("tasks_journal_append_only: ok" if not found else "")
    sys.exit(1 if found else 0)
