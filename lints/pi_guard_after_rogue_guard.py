#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = "pi-guard.ts"
ROGUE = "no-rogue-background.ts"


def lint(root: Path | None = None) -> list[str]:
    names = sorted(path.name for path in ((root or ROOT) / "extensions").glob("*.ts"))
    if GUARD not in names or ROGUE not in names:
        return []
    if names.index(GUARD) < names.index(ROGUE):
        return [
            f"{GUARD} 的 tool_call 钩子先于 {ROGUE} 运行——pi 按文件名字典序依次执行钩子且首个 block 即返回;"
            "包装后的命令以引号结尾,no-rogue-background 的「结尾 &」检测会被绕过,后台化命令重新裸跑"
        ]
    return []


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(f"pi_guard_after_rogue_guard: {item}")
    print("pi_guard_after_rogue_guard: ok" if not found else "")
    sys.exit(1 if found else 0)
