#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_VALUE_IMPORT = re.compile(r'^import\s+\{([^}]+)\}\s+from\s+"(typebox|@earendil-works/[^"]*)"', re.MULTILINE)


def main() -> int:
    extensions = ROOT / "extensions"
    if not extensions.is_dir():
        print("extension_static_typebox: extensions/ 不存在")
        return 1
    violations = []
    for path in sorted(extensions.glob("*.ts")):
        source = path.read_text(errors="ignore")
        if "registerTool" not in source:
            continue
        for match in STATIC_VALUE_IMPORT.finditer(source):
            names = [n.strip() for n in match.group(1).split(",") if n.strip()]
            values = [n for n in names if not n.startswith("type ")]
            if values:
                violations.append(f"{path.name}: 顶层值导入 {match.group(2)}({', '.join(values)}) — 必须 await import 进 async factory(D3-7,driver 裸 node 跑不通)")
    for violation in violations:
        print(f"extension_static_typebox: {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
