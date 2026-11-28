#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELATIVE_IMPORT = re.compile(r"""^import\s[^;]*?\sfrom\s+["']\.{1,2}/""", re.MULTILINE)
DYNAMIC_RELATIVE_IMPORT = re.compile(r"""import\(\s*["']\.{1,2}/""")


def lint(root: Path | None = None) -> list[str]:
    root = root or ROOT
    problems = []
    for path in sorted((root / "extensions").glob("*.ts")):
        source = path.read_text(errors="ignore")
        for pattern in (RELATIVE_IMPORT, DYNAMIC_RELATIVE_IMPORT):
            for match in pattern.finditer(source):
                line = source[: match.start()].count("\n") + 1
                problems.append(f"extensions_self_contained: {path.name}:{line} 相对导入另一个文件——pi 对每个扩展文件用独立 jiti 实例加载(loader.js moduleCache:false),import 拿到的是另一份模块实例,模块级状态永不相通;需要共享状态的代码必须同文件")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    print("extensions_self_contained: ok" if not found else "")
    sys.exit(1 if found else 0)
