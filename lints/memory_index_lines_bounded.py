#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "extensions" / "memory.ts"
    if not path.exists():
        print("memory_index_lines_bounded: extensions/memory.ts 不存在")
        return 1
    source = path.read_text(errors="ignore")
    violations = []
    line_fn = re.search(r"function indexLine\([^)]*\)[^{]*\{(.{0,900}?)\n\}", source, re.DOTALL)
    if not line_fn:
        violations.append("缺少 indexLine 辅助函数——索引行构造必须集中一处受检")
    else:
        body = line_fn.group(1)
        if "DESCRIPTION_INDEX_CHARS" not in body or "slice" not in body:
            violations.append("indexLine 未按 DESCRIPTION_INDEX_CHARS 截断 description——2026-11-08 实测存量索引行 avg 128 字符(≈65 token),30 行吃掉 system prompt 16%,行肥即冗余")
    if "GLOBAL_INDEX_TOP_K" not in source or not re.search(r"slice\(0,\s*GLOBAL_INDEX_TOP_K\)", source):
        violations.append("全局桶索引缺少 GLOBAL_INDEX_TOP_K 截断——43 条全局存量会淹没项目记忆(11-08 诊断:项目 2 条被挤进'其余略')")
    if "PROJECT_INDEX_TOP_K" not in source or not re.search(r"slice\(0,\s*PROJECT_INDEX_TOP_K\)", source):
        violations.append("项目桶索引缺少 PROJECT_INDEX_TOP_K 上限——项目桶理论可膨胀,全量也要有界")
    if violations:
        print(f"memory_index_lines_bounded: {len(violations)} 处违规")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("memory_index_lines_bounded: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
