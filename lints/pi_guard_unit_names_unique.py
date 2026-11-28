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
PI_BASH = Path.home() / ".local" / "lib" / "node_modules" / "@earendil-works" / "pi-coding-agent" / "dist" / "core" / "tools" / "bash.js"
GB = 1024 * 1024 * 1024


def unavailable() -> str | None:
    if not os.environ.get("XDG_RUNTIME_DIR"):
        return "无 XDG_RUNTIME_DIR(无用户级 systemd 总线)"
    if shutil.which("systemd-run") is None or shutil.which("node") is None:
        return "无 systemd-run 或 node"
    if not PI_BASH.exists():
        return "默认路径下无 pi 内置 bash 工具"
    if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
        return "无 cgroup v2"
    probe = subprocess.run(
        ["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit=pi-guard-lint-probe-{os.getpid()}", "--", "/bin/true"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if probe.returncode != 0:
        return f"用户级 systemd 不可用: {probe.stderr.strip()}"
    return None


def drive(spec: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="pi-guard-units-") as scratch:
        result = subprocess.run(
            ["node", "--experimental-strip-types", "--no-warnings", str(DRIVER), "run"],
            input=json.dumps(spec),
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=180,
            env={**os.environ, "TMPDIR": scratch},
        )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])
    return json.loads(result.stdout)


def lint() -> list[str]:
    problems = []
    slice_name = f"piguarduniq{os.getpid()}.slice"
    out = drive(
        {
            "tool": "pi",
            "instances": 2,
            "settleMs": 800,
            "stopSlice": slice_name,
            "config": {"slice": slice_name, "sliceMaxBytes": 2 * GB, "reportMinSec": 1},
            "calls": [[{"id": "first", "via": 0, "command": "sleep 2; echo first-ok"}, {"id": "second", "via": 1, "command": "sleep 2; echo second-ok"}]],
        }
    )
    results = {result["id"]: result for result in out["results"]}
    first = results["first"]
    second = results["second"]
    for name, result in (("first", first), ("second", second)):
        text = "\n".join(result["content"])
        if result["exitCode"] != 0 or f"{name}-ok" not in text or "没有执行" in text:
            problems.append(f"同进程两个扩展实例并发执行时 {name} 命令失败: exit={result['exitCode']} unit={result['unit']}")
    if not first["unit"].startswith("pi-guard-") or not second["unit"].startswith("pi-guard-"):
        problems.append(f"并发实例的命令未被隔离: unit={first['unit']!r} / {second['unit']!r}")
    if first["unit"] == second["unit"]:
        problems.append(f"同进程两个扩展实例生成了相同的 unit 名: {first['unit']}——后启动的命令会因 unit 已存在而失败")
    if not (out["status"] or "").startswith("pi-guard:cgroup 隔离"):
        problems.append(f"并发实例导致隔离模式降级: {out['status']}")
    return problems


if __name__ == "__main__":
    reason = unavailable()
    if reason:
        print(f"pi_guard_unit_names_unique: skip({reason})")
        sys.exit(0)
    try:
        found = lint()
    except (RuntimeError, KeyError, json.JSONDecodeError) as error:
        print(f"pi_guard_unit_names_unique: E2E 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"pi_guard_unit_names_unique: {item}")
    print("pi_guard_unit_names_unique: ok" if not found else "")
    sys.exit(1 if found else 0)
