#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DETAILS_WITH_CURSOR = re.compile(r"details:\s*\{[^}]*\bcursor\b")
CONTENT_TEXT = re.compile(r"content:\s*\[\s*\{\s*type:\s*\"text\"")


def lint(root: Path | None = None) -> list[str]:
    root = root or ROOT
    problems = []
    for path in sorted((root / "extensions").glob("*.ts")):
        text = path.read_text(errors="ignore")
        for match in DETAILS_WITH_CURSOR.finditer(text):
            window = text[max(0, match.start() - 800) : match.end() + 200]
            protocol_visible = "cursor=${" in window or "[cursor=" in window
            if not protocol_visible:
                line = text[: match.start()].count("\n") + 1
                problems.append(
                    f"tool_protocol_fields_in_content: {path.name}:{line} details 含 cursor 协议字段但 content 文本未回显——模型只读 content,协议字段仅进 details 对模型不可见,增量读协议失效"
                )
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    print("tool_protocol_fields_in_content: ok" if not found else "")
    sys.exit(1 if found else 0)
