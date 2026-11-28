#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOREIGN_OWNED = {"a2a-inbox.ts": "a2a-mailbox hub 仓(node-2)"}


def find_foreign_owned(extensions_dir: Path) -> list[str]:
    return sorted(
        f"{name} 归 {owner}管,不得出现在本仓 extensions/"
        for name, owner in FOREIGN_OWNED.items()
        if (extensions_dir / name).exists()
    )


def main() -> int:
    problems = find_foreign_owned(ROOT / "extensions")
    for item in problems:
        print(f"foreign_owned_extensions_absent: {item}")
    print("foreign_owned_extensions_absent: ok" if not problems else "")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
