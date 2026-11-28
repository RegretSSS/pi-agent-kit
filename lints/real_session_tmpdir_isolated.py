#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIGGERS = ("PI_CODING_AGENT_DIR", "pi_guard_driver.mjs")


def finds_real_sessions(source: str) -> bool:
    return any(trigger in source for trigger in TRIGGERS) and "subprocess." in source


def unisolated(repo: Path) -> list[str]:
    problems = []
    for folder in ("lints", "tests"):
        for path in sorted((repo / folder).glob("*.py")):
            source = path.read_text(encoding="utf-8")
            if path.name == Path(__file__).name:
                continue
            if finds_real_sessions(source) and '"TMPDIR"' not in source:
                problems.append(f"{path.relative_to(repo)} 起 pi 子进程却没给它独立的 TMPDIR——pi 的输出转存与 jiti 缓存会落到共享的 /tmp,跑完没人清")
    return problems


def main() -> int:
    problems = unisolated(ROOT)
    for item in problems:
        print(f"real_session_tmpdir_isolated: {item}")
    print("real_session_tmpdir_isolated: ok" if not problems else "")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
