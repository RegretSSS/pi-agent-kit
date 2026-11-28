#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTING_LINE = re.compile(r"^extensions/\s+pi 扩展\((.*)\)\s*$", re.MULTILINE)
SEPARATOR = re.compile(r"\s+/\s+")


def listed_extensions(readme: str) -> list[str] | None:
    match = LISTING_LINE.search(readme)
    return None if match is None else SEPARATOR.split(match.group(1))


def lint(root: Path | None = None) -> list[str]:
    root = root or ROOT
    expected = {path.stem for path in (root / "extensions").glob("*.ts")}
    listed = listed_extensions((root / "README.md").read_text(errors="ignore"))
    if listed is None:
        return ["README「结构」节缺 `extensions/   pi 扩展(a / b / c)` 这一行——它是读者唯一看得到的扩展名单"]
    problems = []
    for name in sorted(expected - set(listed)):
        problems.append(f"README 扩展名单缺 {name}——extensions/ 里有它,读者按 README 找不到(上次漂移:写着四个扩展,其中一个并不存在)")
    for name in sorted(set(listed) - expected):
        problems.append(f"README 扩展名单多了 {name}——extensions/ 里没有这个文件")
    return problems


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(f"readme_extensions_match_dir: {item}")
    print("readme_extensions_match_dir: ok" if not found else "")
    sys.exit(1 if found else 0)
