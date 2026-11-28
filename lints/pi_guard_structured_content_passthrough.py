#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "pi_guard_driver.mjs"


def lint() -> list[str]:
    problems = []
    passthrough = 'return structuredContent === undefined ? { content: parts } : { content: parts, structuredContent };'
    source = (ROOT / "extensions" / "pi-guard.ts").read_text(errors="ignore")
    if passthrough not in source:
        problems.append("tool_result 改写 content 的出口未原样带回 structuredContent——pi 规则:只换 content 会丢弃结构化结果,codemode 脚本读不到 exit_code/output")
    spec = {
        "config": {"systemdRun": "/nonexistent/systemd-run", "reportMinSec": 1},
        "calls": [{"id": "annotated", "command": "sleep 1.2; echo done"}],
    }
    with tempfile.TemporaryDirectory(prefix="pi-guard-passthrough-") as scratch:
        result = subprocess.run(
            ["node", "--experimental-strip-types", "--no-warnings", str(DRIVER), "run"],
            input=json.dumps(spec),
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=120,
            env={**os.environ, "TMPDIR": scratch},
        )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:])
    call = json.loads(result.stdout)["results"][0]
    if len(call["content"]) < 2 or not call["content"][-1].startswith("[pi-guard]"):
        problems.append("回放:长命令回执未追加 [pi-guard] 标注——行为面与规则脱节")
    if call["hookStructured"] is not True:
        problems.append("回放:追加标注后 structuredContent 丢失")
    return problems


if __name__ == "__main__":
    if shutil.which("node") is None:
        print("pi_guard_structured_content_passthrough: skip(无 node)")
        sys.exit(0)
    try:
        found = lint()
    except (RuntimeError, json.JSONDecodeError, KeyError, IndexError) as error:
        print(f"pi_guard_structured_content_passthrough: 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"pi_guard_structured_content_passthrough: {item}")
    print("pi_guard_structured_content_passthrough: ok" if not found else "")
    sys.exit(1 if found else 0)
