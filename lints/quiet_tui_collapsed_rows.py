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
CODEMODE_SCRIPT = "\n".join([
    '// @options: {"timeout_ms": 60000}',
    'const rows = await tools.read({ path: "~/workspace/pi-agent-kit/SPEC.md" });',
    "console.log(rows.length);",
    "for (const row of rows) console.log(row.name);",
])
CODEMODE_CALLS = [
    {"name": "read", "args": '{"path":"~/workspace/pi-agent-kit/SPEC.md"}', "status": "ok", "durationMs": 12},
    {"name": "grep", "args": '{"pattern":"codemode"}', "status": "ok", "durationMs": 1200},
    {"name": "write", "args": '{"path":"/tmp/x"}', "status": "error", "durationMs": 850, "error": "EACCES: permission denied"},
]
CODEMODE_DONE = "Script completed\nWall time 3.2 seconds\nOutput:\n42\n{\"a\":1}\n"
CODEMODE_FAILED = "Script failed\nWall time 3.2 seconds\nOutput:\nScript error:\nTypeError: rows is not iterable\n    at <anonymous>\n\nTool calls made before the failure (they are not undone): read (ok), grep (ok), write (error)"
SCENES = {
    "bash": {"toolName": "bash", "def": "builtin", "args": {"command": "sleep 4; echo X; exit 5"}, "partial": "X\nExit code: 5", "result": {"text": "X\nExit code: 5"}},
    "bash_long": {"toolName": "bash", "def": "builtin", "args": {"command": LONG_COMMAND}, "partial": "l1\nl2\nl3\nl4\nl5", "result": {"text": OUTPUT}},
    "bash_fail": {"toolName": "bash", "def": "builtin", "args": {"command": "cat /none"}, "result": {"text": "cat: /none: No such file or directory\nExit code: 1", "isError": True}},
    "read": {"toolName": "read", "def": "builtin", "args": {"path": "/home/remedy/workspace/x.ts", "offset": 1, "limit": 200}, "result": {"text": OUTPUT}},
    "mcp": {"toolName": "mcp__docs__search", "def": "mcp", "args": {"query": "tool renderer", "limit": 10}, "result": {"text": OUTPUT}},
    "plain": {"toolName": "task_create", "def": "plain", "args": {"cmd": "sleep 4; echo X", "name": "bg-e2e"}, "result": {"text": "[task] bg-e2e started"}},
    "plain_expanded": {"toolName": "bg_list", "def": "plain", "args": {}, "expanded": True, "result": {"text": LISTING}},
    "bash_expanded": {"toolName": "bash", "def": "builtin", "args": {"command": "echo X"}, "expanded": True, "result": {"text": OUTPUT}},
    "codemode": {
        "toolName": "codemode", "def": "codemode", "args": {"code": CODEMODE_SCRIPT}, "partial": "",
        "partialDetails": {"calls": [CODEMODE_CALLS[0], dict(CODEMODE_CALLS[2], status="running", durationMs=None)]},
        "result": {"text": CODEMODE_DONE, "details": {"calls": CODEMODE_CALLS[:2]}},
    },
    "codemode_fail": {
        "toolName": "codemode", "def": "codemode", "args": {"code": CODEMODE_SCRIPT}, "partial": "",
        "partialDetails": {"calls": [CODEMODE_CALLS[0], CODEMODE_CALLS[2], dict(CODEMODE_CALLS[1], status="running", durationMs=None)]},
        "result": {"text": CODEMODE_FAILED, "isError": True, "details": {"calls": CODEMODE_CALLS}},
    },
    "codemode_expanded": {"toolName": "codemode", "def": "codemode", "args": {"code": CODEMODE_SCRIPT}, "expanded": True, "result": {"text": CODEMODE_DONE, "details": {"calls": CODEMODE_CALLS[:2]}}},
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
    folded = ("bash", "bash_long", "bash_fail", "read", "mcp", "plain", "unregistered", "inject", "codemode", "codemode_fail")
    for name in folded:
        final = rendered[name]["final"]
        expected = 3 if name in ("bash_fail", "codemode_fail") else 2
        if final["rows"] != expected or final["text"][0] != "":
            problems.append(f"{name} 折叠态结束时应为 {expected} 行(硬空行 + 摘要行{' + 错误首行' if expected == 3 else ''}),实际 {final['rows']} 行: {final['text'][:3]}")
        if rendered[name]["passthrough"]:
            problems.append(f"{name} 应被 quiet-tui 接管,却原样透传")
    for name, needle in (("bash", "$ sleep 4; echo X; exit 5"), ("bash_long", "$ git -C"), ("read", "read ~/workspace/x.ts:1-200"), ("mcp", "docs/search query=\"tool renderer\" limit=10"), ("plain", "task_create cmd=\"sleep 4; echo X\" name=bg-e2e"), ("unregistered", "gone_tool a=b"), ("codemode", "codemode const rows = await tools.read(")):
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
    summary = rendered["codemode"]["final"]["text"][1]
    if "(+2 lines)" not in summary or "…" not in summary or "console.log" in summary or "@options" in summary:
        problems.append(f"codemode 摘要行应是脚本首个有效行截断加余下行数: {summary!r}")
    running = rendered["codemode"]["running"]
    if running["rows"] != 3 or not all(part in running["text"][2] for part in ("2 calls", "…", "write")):
        problems.append(f"codemode 运行中应给一行嵌套调用进度: {running}")
    failed = rendered["codemode_fail"]
    if "3 calls" not in failed["running"]["text"][2] or "1 failed" not in failed["running"]["text"][2] or "grep" not in failed["running"]["text"][2]:
        problems.append(f"codemode 有嵌套调用失败时进度行应点名: {failed['running']}")
    if "✗" not in failed["final"]["text"][1] or "TypeError: rows is not iterable" not in failed["final"]["text"][2]:
        problems.append(f"codemode 失败时应给出 ✗ 与剥掉脚本头的错误首行: {failed['final']}")
    expanded = "\n".join(rendered["codemode_expanded"]["final"]["text"])
    if rendered["codemode_expanded"]["final"]["rows"] <= 2 or not all(part in expanded for part in ("const rows = await tools.read", "console.log(rows.length)", "✓ read", "✓ grep", "42", '{"a":1}')):
        problems.append(f"codemode 展开后应委托回 pi 原渲染器给出代码、嵌套调用与输出: {expanded}")
    pages = drive("export", ["bash_expanded", "plain", "bash_fail", "codemode_expanded", "codemode_fail"])["pages"]
    if "line of output text number 30" not in pages["bash_expanded"]["expanded"] or pages["bash_expanded"]["collapsed"]:
        problems.append(f"HTML 导出应直接给出 bash 全文: {pages['bash_expanded']}")
    if not all(part in pages["codemode_expanded"]["expanded"] for part in ("✓ grep", "42", '{"a":1}')) or pages["codemode_expanded"]["collapsed"]:
        problems.append(f"HTML 导出应直接给出 codemode 的嵌套调用与输出全文: {pages['codemode_expanded']}")
    if "TypeError: rows is not iterable" not in pages["codemode_fail"]["collapsed"] or "Script error:" not in pages["codemode_fail"]["expanded"]:
        problems.append(f"HTML 导出的 codemode 失败态应给出错误首行: {pages['codemode_fail']}")
    if len(pages["codemode_expanded"]["call"].splitlines()) != 1 or "(+2 lines)" not in pages["codemode_expanded"]["call"]:
        problems.append(f"HTML 导出的 codemode 调用头应是单行摘要: {pages['codemode_expanded']['call']!r}")
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
