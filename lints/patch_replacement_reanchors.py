#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCH_SCRIPTS = sorted((ROOT / "scripts").glob("patch-*.mjs"))
IMPORT_LINE = re.compile(r'^import\s*\{([^}]*)\}\s*from\s*"([^"]+)";$', re.MULTILINE)


def split_args(call_body: str) -> list[str] | None:
    args: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    for ch in call_body:
        if quote is not None:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            current.append(ch)
            continue
        if ch in "([{":
            depth += 1
            current.append(ch)
            continue
        if ch in ")]}":
            depth -= 1
            if depth < 0:
                args.append("".join(current).strip())
                return args if len(args) >= 5 else None
            current.append(ch)
            continue
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    return None


def find_calls(source: str) -> list[list[str]]:
    calls = []
    at = source.find("patchFile(")
    while at >= 0:
        if at >= 9 and source[at - 9 : at] == "function ":
            at = source.find("patchFile(", at + 1)
            continue
        body = source[at + len("patchFile(") :]
        args = split_args(body)
        if args is not None:
            span = source[at:]
            calls.append(args + [span[: span.find("\n") + 1] or "patchFile(...)"])
        at = source.find("patchFile(", at + 1)
    return calls


def resolve_consts(source: str) -> dict[str, str]:
    cut = source.find("function patchFile")
    if cut < 0:
        return {}
    header = source[:cut]
    header = IMPORT_LINE.sub(lambda m: f'const {{{m.group(1)}}} = require("{m.group(2)}");', header)
    names = re.findall(r"^const ([A-Z_][A-Z0-9_]*) = ", header, re.MULTILINE)
    node_code = header + "\nconsole.log(JSON.stringify({" + ", ".join(f'"{n}": String({n})' for n in names) + "}));"
    result = subprocess.run(["node", "-e", node_code], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"node eval 失败: {result.stderr[:400]}")
    return json.loads(result.stdout)


def unquote(arg: str, consts: dict[str, str]) -> str | None:
    arg = arg.strip()
    if len(arg) >= 2 and arg[0] in "\"'" and arg[-1] == arg[0]:
        return arg[1:-1].replace('\\"', '"').replace("\\'", "'").replace("\\n", "\n").replace("\\\\", "\\")
    parts = [p.strip() for p in arg.split("+")]
    values = []
    for part in parts:
        if part in consts:
            values.append(consts[part])
        elif len(part) >= 2 and part[0] in "\"'" and part[-1] == part[0]:
            values.append(unquote(part, consts) or "")
        else:
            return None
    return "".join(values)


def main() -> int:
    violations = []
    checked = 0
    for path in PATCH_SCRIPTS:
        source = path.read_text(encoding="utf-8")
        calls = find_calls(source)
        if not calls:
            continue
        consts = resolve_consts(source)
        for args in calls:
            anchor, repl, marker = args[1], args[2], args[3]
            anchor_val = unquote(anchor, consts)
            repl_val = unquote(repl, consts)
            marker_val = unquote(marker, consts)
            checked += 1
            if anchor_val is None or repl_val is None or marker_val is None:
                violations.append(f"{path.name}: 实参未能求值({anchor}/{repl}/{marker})")
                continue
            if anchor_val not in repl_val and marker_val not in repl_val:
                violations.append(
                    f"{path.name}: replacement({repl.strip()}) 既不含 anchor 也不含 marker——"
                    f"已 patch 机器上锚点被吃掉,后继 patchFile 与幂等重跑都会锚点失配"
                )
    if checked == 0:
        print("patch_replacement_reanchors: 没有 patchFile 调用可查(结构漂移?)")
        return 1
    if violations:
        print("patch_replacement_reanchors: " + "; ".join(violations))
        return 1
    print(f"patch_replacement_reanchors: {checked} 个注入点 replacement 均保持锚点存活")
    return 0


if __name__ == "__main__":
    sys.exit(main())
