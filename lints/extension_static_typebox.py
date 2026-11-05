#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_VALUE_IMPORT = re.compile(
    r'^import\s+(?!type\b)(?:\w+\s*,\s*)?(?:\{([^}]*)\}|(\w+)|\*\s+as\s+\w+)\s+from\s+[\'"](typebox|@earendil-works/[^\'"]*)[\'"]',
    re.MULTILINE,
)


def main() -> int:
    extensions = ROOT / "extensions"
    if not extensions.is_dir():
        print("extension_static_typebox: extensions/ 不存在")
        return 1
    violations = []
    for path in sorted(extensions.glob("*.ts")):
        source = path.read_text(errors="ignore")
        for match in STATIC_VALUE_IMPORT.finditer(source):
            named = match.group(1)
            if named is not None:
                names = [n.strip() for n in named.split(",") if n.strip()]
                values = [n for n in names if not n.startswith("type ")]
                if not values:
                    continue
            else:
                values = [match.group(2) or "* as ns"]
            violations.append(f"{path.name}: 顶层值导入 {match.group(3)}({', '.join(values)}) — 必须 await import 进 async factory(D3-7,driver 裸 node 跑不通)")
    for violation in violations:
        print(f"extension_static_typebox: {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
