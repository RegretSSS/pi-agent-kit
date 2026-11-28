#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "quiet_tui_driver.mjs"
OUTPUT = "\n".join(f"line of output text number {index}" for index in range(1, 31))
LISTING = "\n".join(f"[task] bg-e2e running #{index}" for index in range(1, 13))
LONG_COMMAND = "git -C ~/workspace/pi-subagents-kit log --oneline -8 kit && echo '--- 部署位 ---' && ls -la ~/.pi/agent/extensions/ | head -40"
SCENES = {
    "bash": {"toolName": "bash", "def": "builtin", "args": {"command": "sleep 4; echo X; exit 5"}, "partial": "X\nExit code: 5", "result": {"text": "X\nExit code: 5"}},
    "bash_long": {"toolName": "bash", "def": "builtin", "args": {"command": LONG_COMMAND}, "partial": "l1\nl2\nl3\nl4\nl5", "result": {"text": OUTPUT}},
    "bash_fail": {"toolName": "bash", "def": "builtin", "args": {"command": "cat /none"}, "result": {"text": "cat: /none: No such file or directory\nExit code: 1", "isError": True}},
    "read": {"toolName": "read", "def": "builtin", "args": {"path": "/home/remedy/workspace/x.ts", "offset": 1, "limit": 200}, "result": {"text": OUTPUT}},
    "mcp": {"toolName": "mcp__docs__search", "def": "mcp", "args": {"query": "tool renderer", "limit": 10}, "result": {"text": OUTPUT}},
    "plain": {"toolName": "task_create", "def": "plain", "args": {"cmd": "sleep 4; echo X", "name": "bg-e2e"}, "result": {"text": "[task] bg-e2e started"}},
    "plain_expanded": {"toolName": "bg_list", "def": "plain", "args": {}, "expanded": True, "result": {"text": LISTING}},
    "bash_expanded": {"toolName": "bash", "def": "builtin", "args": {"command": "echo X"}, "expanded": True, "result": {"text": OUTPUT}},
    "custom": {"toolName": "Agent", "def": "custom", "args": {"prompt": "x"}, "result": {"text": "agent result"}},
    "unregistered": {"toolName": "gone_tool", "def": "unregistered", "args": {"a": "b"}, "result": {"text": "old output"}},
    "inject": {"toolName": "bash", "def": "builtin", "args": {"command": "echo hi\x1b]0;pwn\x07\nsecond\x1b[31m"}, "result": {"text": "ok"}},
}


def pi_package_root() -> Path | None:
    binary = shutil.which("pi") or str(Path.home() / ".local" / "bin" / "pi")
    if not Path(binary).exists():
        return None
    for parent in Path(binary).resolve().parents:
        if (parent / "node_modules" / "typebox" / "package.json").exists():
            return parent
    return None


def drive(scenario: str, names: list[str]) -> dict:
    root = pi_package_root()
    if root is None:
        raise LookupError("找不到已安装的 pi 包根")
    scenes = [{**SCENES[name], "name": name} for name in names]
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(DRIVER), scenario],
        input=json.dumps({"scenes": scenes}),
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
        env={**os.environ, "PI_PACKAGE_ROOT": str(root)},
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:])
    return json.loads(result.stdout)


def lint() -> list[str]:
    problems = []
    rendered = drive("render", list(SCENES))["results"]
    folded = ("bash", "bash_long", "bash_fail", "read", "mcp", "plain", "unregistered", "inject")
    for name in folded:
        final = rendered[name]["final"]
        expected = 3 if name == "bash_fail" else 2
        if final["rows"] != expected or final["text"][0] != "":
            problems.append(f"{name} 折叠态结束时应为 {expected} 行(硬空行 + 摘要行{' + 错误首行' if name == 'bash_fail' else ''}),实际 {final['rows']} 行: {final['text'][:3]}")
        if rendered[name]["passthrough"]:
            problems.append(f"{name} 应被 quiet-tui 接管,却原样透传")
    for name, needle in (("bash", "$ sleep 4; echo X; exit 5"), ("bash_long", "$ git -C"), ("read", "read ~/workspace/x.ts:1-200"), ("mcp", "docs/search query=\"tool renderer\" limit=10"), ("plain", "task_create cmd=\"sleep 4; echo X\" name=bg-e2e"), ("unregistered", "gone_tool a=b")):
        if needle not in rendered[name]["final"]["text"][1]:
            problems.append(f"{name} 摘要行应含 {needle!r}: {rendered[name]['final']['text'][1]}")
    if "✓ 1.2s" not in rendered["bash"]["final"]["text"][1]:
        problems.append(f"成功调用的摘要行应带耗时: {rendered['bash']['final']['text'][1]}")
    if "…" not in rendered["bash_long"]["final"]["text"][1]:
        problems.append("超宽命令应截断加省略号")
    if not rendered["bash"]["before"]["text"][1].endswith("…") or " …" in rendered["bash"]["running"]["text"][1]:
        problems.append("参数未收尾时行尾应有省略号,收尾后不得残留")
    running = rendered["bash_long"]["running"]
    if running["rows"] != 5 or [line.strip() for line in running["text"][2:]] != ["l3", "l4", "l5"]:
        problems.append(f"bash 运行中应显示末 3 行预览: {running['text']}")
    failed = rendered["bash_fail"]["final"]["text"]
    if "✗" not in failed[1] or "cat: /none: No such file or directory" not in failed[2]:
        problems.append(f"失败调用应给出 ✗ 与错误首行: {failed}")
    injected = rendered["inject"]["final"]["text"]
    leaked = any(any(ord(char) < 32 and char != "\t" or ord(char) == 127 for char in line) for line in injected)
    if rendered["inject"]["final"]["rows"] != 2 or leaked or "pwn" in injected[1] or "echo hi second" not in injected[1]:
        problems.append(f"参数里的 OSC/CSI/换行应被清成单行: {injected}")
    if not rendered["custom"]["passthrough"] or rendered["custom"]["final"]["rows"] <= 2:
        problems.append("自带渲染器的工具应原样透传")
    if rendered["plain_expanded"]["final"]["rows"] < 14 or "[task] bg-e2e running #12" not in "\n".join(rendered["plain_expanded"]["final"]["text"]):
        problems.append("无自带渲染器的工具展开后应看到全文")
    if "line of output text number 30" not in "\n".join(rendered["bash_expanded"]["final"]["text"]):
        problems.append("内建工具展开后应委托回 pi 原渲染器给出全文")
    pages = drive("export", ["bash_expanded", "plain", "bash_fail"])["pages"]
    if "line of output text number 30" not in pages["bash_expanded"]["expanded"] or pages["bash_expanded"]["collapsed"]:
        problems.append(f"HTML 导出应直接给出 bash 全文: {pages['bash_expanded']}")
    if not pages["plain"]["fallback"]:
        problems.append(f"HTML 导出对无渲染器的工具应回落到结构化结果: {pages['plain']}")
    if "cat: /none" not in pages["bash_fail"]["expanded"]:
        problems.append(f"HTML 导出应保留失败原因: {pages['bash_fail']}")
    if len(pages["bash_expanded"]["call"].splitlines()) != 1 or "$ echo X" not in pages["bash_expanded"]["call"]:
        problems.append(f"HTML 导出的调用头应是单行摘要: {pages['bash_expanded']['call']!r}")
    return problems


if __name__ == "__main__":
    if shutil.which("node") is None or pi_package_root() is None:
        print("quiet_tui_collapsed_rows: skip(无 node 或无已安装的 pi)")
        sys.exit(0)
    try:
        found = lint()
    except (LookupError, RuntimeError, json.JSONDecodeError, KeyError, IndexError, subprocess.TimeoutExpired) as error:
        print(f"quiet_tui_collapsed_rows: 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"quiet_tui_collapsed_rows: {item}")
    print("quiet_tui_collapsed_rows: ok" if not found else "")
    sys.exit(1 if found else 0)
