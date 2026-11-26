#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "pi_guard_driver.mjs"
PI_BASH = Path.home() / ".local" / "lib" / "node_modules" / "@earendil-works" / "pi-coding-agent" / "dist" / "core" / "tools" / "bash.js"
MB = 1024 * 1024
LINE = "[apigate] 收到 429：该调用让出并发槽排队等待，并发容量降为 1（30 秒后重试）"


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
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(DRIVER), "run"],
        input=json.dumps(spec),
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])
    return json.loads(result.stdout)


def hot_loop(seconds: int) -> str:
    return "python3 - <<'EOF' 2>&1\nimport sys, time\nend = time.time() + %d\nwhile time.time() < end:\n    sys.stdout.write(%r + \"\\n\")\nEOF" % (seconds, LINE)


def reading_loop(seconds: int) -> str:
    return "python3 - <<'EOF' 2>&1\nimport os, sys, time\nend = time.time() + %d\nfd = os.open('/etc/services', os.O_RDONLY)\nwhile time.time() < end:\n    os.pread(fd, 4096, 0)\n    sys.stdout.write(%r + \"\\n\")\nEOF" % (seconds, LINE)


def grower() -> str:
    return "python3 - <<'EOF'\nimport time\nblocks = []\nwhile True:\n    blocks.append(b\"x\" * (50 * 1024 * 1024))\n    time.sleep(0.2)\nEOF"


def plateau(size_mb: int, hold_sec: int) -> str:
    return "python3 - <<'EOF'\nimport time\nblock = bytearray(%d * 1024 * 1024)\nblock[::4096] = b\"x\" * (len(block) // 4096)\ntime.sleep(%d)\nprint(\"plateau ok\")\nEOF" % (size_mb, hold_sec)


def by_id(out: dict, call_id: str) -> dict:
    return next(result for result in out["results"] if result["id"] == call_id)


def texts(result: dict) -> str:
    return "\n".join(result["content"])


def lint() -> list[str]:
    problems = []
    tag = os.getpid()
    small = f"piguardtest{tag}a.slice"
    roomy = f"piguardtest{tag}b.slice"
    base = {"tickMs": 50, "rateWindowMs": 500, "spinWindowSec": 3, "reportMinSec": 1}
    first = drive(
        {
            "tool": "pi",
            "settleMs": 800,
            "stopSlice": small,
            "limitsDuringLastCall": True,
            "config": {**base, "slice": small, "sliceMaxBytes": 150 * MB},
            "calls": [
                {"id": "ceiling", "command": grower()},
                {"id": "plateau", "command": plateau(100, 2)},
                [{"id": "runaway", "command": grower()}, {"id": "neighbor", "command": "sleep 3; echo neighbor-alive"}],
                {"id": "linger", "command": "sleep 1.5"},
            ],
        }
    )
    if not (first["status"] or "").startswith("pi-guard:cgroup 隔离"):
        problems.append(f"E2E 未进入 cgroup 隔离模式: {first['status']}")
    if first["limitsDuringLastCall"] != {"memoryMax": str(150 * MB), "memorySwapMax": "0"}:
        problems.append(f"命令运行期间测试 slice 限额不生效: {first['limitsDuringLastCall']}")
    if first["sliceDir"] is None or not first["sliceDir"].endswith(f"/{small}") or "piguard.slice" in first["sliceDir"]:
        problems.append(f"测试 slice 必须独立于生产 slice: {first['sliceDir']}")
    ceiling = by_id(first, "ceiling")
    if ceiling["exitCode"] != 137 or "[pi-guard] 已停止:内存涨到硬顶" not in texts(ceiling):
        problems.append(f"涨到硬顶的命令未被内核终止或未回执: exit={ceiling['exitCode']}")
    plateau_result = by_id(first, "plateau")
    if plateau_result["exitCode"] != 0 or "已停止" in texts(plateau_result):
        problems.append(f"硬顶内持平的合法大内存被误杀: exit={plateau_result['exitCode']}")
    runaway = by_id(first, "runaway")
    neighbor = by_id(first, "neighbor")
    if runaway["exitCode"] != 137 or "[pi-guard] 已停止:内存涨到硬顶" not in texts(runaway):
        problems.append(f"并发场景失控命令未被终止: exit={runaway['exitCode']}")
    if neighbor["exitCode"] != 0 or "neighbor-alive" not in texts(neighbor):
        problems.append(f"并发场景无辜邻居被误杀: exit={neighbor['exitCode']}")
    if any(line["mode"] != "contained" or not line["unit"].startswith("pi-guard-") for line in first["log"]):
        problems.append("日志未记录 contained 模式或 unit 名")
    if sorted(line["verdict"] for line in first["log"] if line["verdict"] != "normal") != ["accumulate", "accumulate"]:
        problems.append(f"硬顶裁决计数不符: {[line['verdict'] for line in first['log']]}")
    if any(line["action"] != "kernel-oom" for line in first["log"] if line["verdict"] == "accumulate"):
        problems.append("内核 OOM 终止的命令 action 应记为 kernel-oom")
    if any(result["hookStructured"] is not True for result in first["results"] if len(result["content"]) > 1):
        problems.append("回执改写 content 时丢失 structuredContent")

    second = drive(
        {
            "tool": "pi",
            "settleMs": 800,
            "stopSlice": roomy,
            "config": {**base, "slice": roomy, "sliceMaxBytes": 2 * 1024 * MB},
            "calls": [
                [
                    {"id": "spin", "command": hot_loop(10)},
                    {"id": "reads", "command": reading_loop(10)},
                    {"id": "bounded", "command": "timeout 60 " + hot_loop(10)},
                ]
            ],
        }
    )
    spin = by_id(second, "spin")
    if spin["exitCode"] != 137 or "[pi-guard] 已停止:空转热循环" not in texts(spin) or "已折叠" not in texts(spin):
        problems.append(f"空转热循环未被停止或未折叠回执: exit={spin['exitCode']}")
    if spin["durationMs"] > 9500:
        problems.append(f"空转判定过慢: {spin['durationMs']}ms")
    for call_id in ("reads", "bounded"):
        result = by_id(second, call_id)
        if result["exitCode"] != 0 or "已停止" in texts(result):
            problems.append(f"{call_id} 场景不应被停止: exit={result['exitCode']}")
    spin_lines = [line for line in second["log"] if line["verdict"] == "spin"]
    if len(spin_lines) != 1 or spin_lines[0]["action"] != "kill-spin":
        problems.append(f"空转裁决未入日志: {[line['verdict'] for line in second['log']]}")
    if sorted(line["verdict"] for line in second["log"] if line["durationMs"] >= 9000) != ["normal", "normal"]:
        problems.append("只读输入/带 timeout 的循环被误判")
    return problems


if __name__ == "__main__":
    reason = unavailable()
    if reason:
        print(f"pi_guard_e2e_containment: skip({reason})")
        sys.exit(0)
    try:
        found = lint()
    except (RuntimeError, StopIteration, KeyError, json.JSONDecodeError) as error:
        print(f"pi_guard_e2e_containment: E2E 执行失败: {error}")
        sys.exit(1)
    for item in found:
        print(f"pi_guard_e2e_containment: {item}")
    print("pi_guard_e2e_containment: ok" if not found else "")
    sys.exit(1 if found else 0)
