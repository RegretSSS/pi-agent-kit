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


def unit() -> dict:
    with tempfile.TemporaryDirectory(prefix="pi-guard-signature-") as scratch:
        result = subprocess.run(
            ["node", "--experimental-strip-types", "--no-warnings", str(DRIVER), "unit"],
            input="{}",
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=120,
            env={**os.environ, "TMPDIR": scratch},
        )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:])
    return json.loads(result.stdout)


def lint() -> list[str]:
    problems = []
    replay = unit()
    spin = replay["spin"]
    signature = replay["signature"]
    ceiling = replay["ceiling"]
    if spin["killAt"] is None:
        problems.append("空转签名正例(重复行+高输出+不读输入+无 timeout 内联脚本)未被停止——判型链路失效")
    for name in ("diverse", "readsInput", "lowOutput", "notEligible", "tooFewLines"):
        if spin[name] != 0:
            problems.append(f"空转负例 {name} 被误停——停命令必须同时满足全部签名条件")
    if ceiling["kernelHandles"] != 0 or ceiling["observed"] != [{"tick": 3, "action": "kill-ceiling"}]:
        problems.append("内存硬顶动作越界——隔离模式必须交给内核,仅观测模式才允许用户态兜底")
    if signature["longDiverse"] != 0 or signature["longVerdict"] != "normal":
        problems.append("按时长或输出量误杀——50 分钟多样输出的合法命令被停或被改判")
    if signature["longSilent"] != 0:
        problems.append("按时长误杀——安静长命令被停")
    if signature["bigFlatContained"] != 0:
        problems.append("按内存大小误杀——涨上去后持平的合法大内存被用户态停掉")
    if signature["singleCore"] != 0 or not signature["singleCoreFlagged"] or signature["singleCoreVerdict"] != "spin-suspect":
        problems.append("纯空转(单核满载内存平)必须只记录不停——动作与标注不符")
    return problems


if __name__ == "__main__":
    if shutil.which("node") is None:
        print("pi_guard_kill_needs_signature: skip(无 node)")
        sys.exit(0)
    try:
        found = lint()
    except (RuntimeError, json.JSONDecodeError, KeyError) as error:
        print(f"pi_guard_kill_needs_signature: 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"pi_guard_kill_needs_signature: {item}")
    print("pi_guard_kill_needs_signature: ok" if not found else "")
    sys.exit(1 if found else 0)
