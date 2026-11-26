import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "pi_guard_driver.mjs"
MB = 1024 * 1024
LINE = "[apigate] 收到 429：该调用让出并发槽排队等待，并发容量降为 1（30 秒后重试）"
OBSERVED = {"systemdRun": "/nonexistent/systemd-run", "tickMs": 50, "rateWindowMs": 500, "spinWindowSec": 1, "reportMinSec": 1}


def drive(mode: str, spec: dict | None = None) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(DRIVER), mode],
        input=json.dumps(spec or {}),
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def hot_loop(seconds: int) -> str:
    return "python3 - <<'EOF' 2>&1\nimport sys, time\nend = time.time() + %d\nwhile time.time() < end:\n    sys.stdout.write(%r + \"\\n\")\nEOF" % (seconds, LINE)


def reading_loop(seconds: int) -> str:
    return "python3 - <<'EOF' 2>&1\nimport os, sys, time\nend = time.time() + %d\nfd = os.open('/etc/services', os.O_RDONLY)\nwhile time.time() < end:\n    os.pread(fd, 4096, 0)\n    sys.stdout.write(%r + \"\\n\")\nEOF" % (seconds, LINE)


def grower() -> str:
    return "python3 - <<'EOF'\nimport time\nblocks = []\nwhile True:\n    blocks.append(b\"x\" * (50 * 1024 * 1024))\n    time.sleep(0.1)\nEOF"


def plateau(size_mb: int, hold_sec: int) -> str:
    return "python3 - <<'EOF'\nimport time\nblock = bytearray(%d * 1024 * 1024)\nblock[::4096] = b\"x\" * (len(block) // 4096)\ntime.sleep(%d)\nprint(\"plateau ok\")\nEOF" % (size_mb, hold_sec)


def by_id(out: dict, call_id: str) -> dict:
    return next(result for result in out["results"] if result["id"] == call_id)


def texts(result: dict) -> str:
    return "\n".join(result["content"])


@pytest.fixture(scope="module")
def unit() -> dict:
    return drive("unit")


class TestShellQuoteAndWrap:
    def test_quote_round_trips_through_sh(self, unit: dict) -> None:
        assert all(item["roundTrip"] for item in unit["shq"])
        assert next(item for item in unit["shq"] if item["value"] == "it's")["quoted"] == "'it'\\''s'"

    def test_wrap_shape_and_marker(self, unit: dict) -> None:
        wrap = unit["wrap"]
        assert wrap["unit"] == "pi-guard-4242-a1b2c3-7"
        assert wrap["wrapped"].startswith(
            "exec '/usr/bin/systemd-run' --user --scope --quiet --collect --unit=pi-guard-4242-a1b2c3-7 --slice=piguard.slice "
            "-p MemorySwapMax=0 -p TasksMax=4096 -- '/usr/bin/env' -u INVOCATION_ID SHLVL=$((SHLVL - 1)) '/bin/bash' -c "
        )
        assert wrap["wrapped"].endswith("'echo '\\''it'\\'' \"is\" $HOME'")
        assert wrap["marker"] is True
        assert wrap["plainMarked"] is True
        assert "-p MemoryMax" not in wrap["wrapped"]
        assert "MemoryOOMGroup" not in wrap["wrapped"]

    def test_wrap_refuses_oversize_single_argument(self, unit: dict) -> None:
        wrap = unit["wrap"]
        assert wrap["smallFits"] is True
        assert wrap["hugeFits"] is False
        assert wrap["quoteHeavyFits"] is False
        assert wrap["quoteHeavyBytes"] > 131000

    def test_wrap_preserves_shlvl_and_strips_invocation_id(self, unit: dict) -> None:
        parity = unit["wrapParity"]
        assert parity["sameOutput"] is True
        assert parity["sameStatus"] is True
        assert "inv=none" in parity["offset"]


class TestCommandClassification:
    def test_inline_script_detection(self, unit: dict) -> None:
        mismatches = [item for item in unit["inline"] if item["expected"] != item["actual"]]
        assert mismatches == []

    def test_explicit_time_bound_detection(self, unit: dict) -> None:
        assert [item for item in unit["bounded"] if item["expected"] != item["actual"]] == []


class TestOutputShape:
    def test_dominant_line_stats(self, unit: dict) -> None:
        assert [item["repetitive"] for item in unit["dominant"]] == [item["expected"] for item in unit["dominant"]]
        assert all(item["fraction"] >= item["fractionAtLeast"] for item in unit["dominant"])


class TestSpinJudgement:
    def test_kills_only_on_sustained_repetitive_output_without_reads(self, unit: dict) -> None:
        spin = unit["spin"]
        assert spin["killAt"] == spin["expectedKillTick"]
        assert spin["counterLines"] == spin["expectedKillTick"]
        assert spin["diverse"] == 0
        assert spin["readsInput"] == 0
        assert spin["lowOutput"] == 0
        assert spin["notEligible"] == 0
        assert spin["tooFewLines"] == 0

    def test_streak_survives_isolated_quiet_ticks_and_resets_on_breaks(self, unit: dict) -> None:
        spin = unit["spin"]
        first = spin["expectedKillTick"]
        assert spin["silentAt"] == first
        assert spin["staleAt"] == first + 21
        assert spin["resumedAt"] == first + 79

    def test_userspace_ceiling_only_when_uncontained(self, unit: dict) -> None:
        assert unit["ceiling"] == {"observed": [{"tick": 3, "action": "kill-ceiling"}], "kernelHandles": 0}

    def test_single_core_suspect_needs_flat_memory(self, unit: dict) -> None:
        assert unit["suspect"] == {"singleCoreFlat": True, "halfCore": False, "singleCoreRising": False, "bursty": False}

    def test_leak_needs_sustained_rising_floor(self, unit: dict) -> None:
        leak = unit["leak"]
        assert leak["rising"] == {"verdict": "leak-suspect", "slopeMBps": 2}
        assert leak["fastEnoughButShort"] == {"verdict": "normal", "slopeMBps": None}
        assert leak["slow"]["verdict"] == "normal"
        assert leak["flat"]["verdict"] == "normal"
        assert leak["sawtooth"]["verdict"] == "normal"


class TestVerdictsAndReceipts:
    def test_ceiling_kill_attribution(self, unit: dict) -> None:
        finalize = unit["finalize"]
        assert finalize["oomKilled"] == "accumulate"
        assert finalize["ceiling"] == "accumulate"
        assert finalize["oomFailedOther"] != "accumulate"
        assert finalize["oomExitedZero"] != "accumulate"
        assert finalize["oomLongAgo"] != "accumulate"
        assert finalize["spinWins"] == "spin"

    def test_annotation_texts(self, unit: dict) -> None:
        annotation = unit["annotation"]
        assert "已停止:空转热循环" in annotation["spin"]
        assert LINE[:20] in annotation["spin"]
        assert "timeout" in annotation["spin"]
        assert "硬顶" in annotation["accumulate"]
        assert "请重试" in annotation["wrapFailed"]
        assert annotation["quiet"] is None
        assert "用量" in annotation["longNormal"]
        assert annotation["untracked"] is None

    def test_repetitive_tail_is_folded_and_status_kept(self, unit: dict) -> None:
        fold = unit["fold"]
        assert fold["repetitive"].startswith("…(300 行重复")
        assert fold["repetitive"].endswith("Command exited with code 137")
        assert len(fold["repetitive"]) < 400
        assert fold["diverse"] is None

    def test_logging_predicate(self, unit: dict) -> None:
        assert unit["shouldLog"] == [False, True, True, True]


class TestConfig:
    def test_invalid_values_fall_back_to_defaults(self, unit: dict) -> None:
        assert unit["config"]["merged"] == {
            "enabled": True,
            "reserveFrac": 0.5,
            "sliceMaxBytes": 123,
            "slice": "piguard.slice",
            "spinWindowSec": 1,
            "tickMs": 50,
            "repeatFrac": 1,
            "maxInBytesPerSec": 20480,
        }

    def test_ceiling_derives_from_total_memory_unless_overridden(self, unit: dict) -> None:
        assert unit["config"]["maxFromTotal"] == 12884901888
        assert unit["config"]["maxOverride"] == 1000

    def test_file_loading(self, unit: dict) -> None:
        config = unit["config"]
        assert config["missing"] == 60
        assert config["malformed"] is True
        assert config["valid"] == {"enabled": False, "sliceMax": config["valid"]["expected"], "expected": config["valid"]["expected"]}


class TestProcessTable:
    def test_tree_leaders_and_freshness(self, unit: dict) -> None:
        processes = unit["processes"]
        assert processes["tree"] == [20, 30, 40]
        assert processes["missing"] == []
        assert processes["leader"] == [True, True, False, True, True]
        assert processes["startedAt"] == 6000
        assert processes["fresh"] == [20, 60]
        assert processes["knownExcluded"] == [20]
        assert processes["tooOld"] == []

    def test_proc_field_parsing(self, unit: dict) -> None:
        assert unit["processes"]["statusFields"] == [31896, 5, 3, 4096]

    def test_recent_log_tail(self, unit: dict) -> None:
        lines = unit["recentLog"]
        assert len(lines) == 10
        assert lines[0].endswith("2ms peak=2MB cmd 2")
        assert lines[-1].endswith("11ms peak=11MB cmd 11")


class TestObservedMode:
    def test_hot_loop_is_stopped_and_quiet_commands_untouched(self) -> None:
        out = drive("run", {"config": OBSERVED, "calls": [{"id": "quiet", "command": "echo hi"}, {"id": "spin", "command": hot_loop(8)}]})
        quiet = by_id(out, "quiet")
        assert quiet["content"] == ["hi\n"]
        assert quiet["rewritten"] is False
        spin = by_id(out, "spin")
        assert spin["exitCode"] == 137
        assert spin["durationMs"] < 4000
        assert "已折叠" in texts(spin)
        assert "[pi-guard] 已停止:空转热循环" in texts(spin)
        assert spin["hookStructured"] is True
        assert any(note["type"] == "warning" and "空转热循环" in note["message"] for note in out["notes"])
        entry = next(line for line in out["log"] if line["verdict"] == "spin")
        assert entry["action"] == "kill-spin"
        assert entry["mode"] == "observed"
        assert entry["outKBps"] >= 100
        assert entry["inKBps"] <= 20

    def test_reading_bounded_and_non_inline_loops_are_left_alone(self) -> None:
        calls = [
            [
                {"id": "reads", "command": reading_loop(3)},
                {"id": "bounded", "command": "timeout 60 " + hot_loop(3)},
                {"id": "noninline", "command": f"timeout 3 yes '{LINE}'"},
            ]
        ]
        out = drive("run", {"config": OBSERVED, "calls": calls})
        for call_id in ("reads", "bounded"):
            assert by_id(out, call_id)["exitCode"] == 0, call_id
        assert by_id(out, "noninline")["exitCode"] == 124
        for call_id in ("reads", "bounded", "noninline"):
            assert "已停止" not in texts(by_id(out, call_id)), call_id
        assert by_id(out, "reads")["durationMs"] >= 2800
        verdicts = {line["cmd"][:9]: line["verdict"] for line in out["log"]}
        assert set(verdicts.values()) == {"normal"}

    def test_userspace_ceiling_stops_growth_but_not_plateau(self) -> None:
        config = {**OBSERVED, "sliceMaxBytes": 200 * MB}
        out = drive("run", {"config": config, "calls": [{"id": "grow", "command": grower()}, {"id": "hold", "command": plateau(100, 2)}]})
        grow = by_id(out, "grow")
        assert grow["exitCode"] == 137
        assert "[pi-guard] 已停止:内存涨到硬顶" in texts(grow)
        hold = by_id(out, "hold")
        assert hold["exitCode"] == 0
        assert "plateau ok" in texts(hold)
        assert "已停止" not in texts(hold)

    def test_big_memory_that_finishes_normally_is_only_recorded(self) -> None:
        config = {**OBSERVED, "bigAnonBytes": 50 * MB}
        out = drive("run", {"config": config, "calls": [{"id": "big", "command": plateau(100, 2)}]})
        big = by_id(out, "big")
        assert big["exitCode"] == 0
        assert "[pi-guard] 记录:大内存任务结束" in texts(big)
        assert out["log"][0]["verdict"] == "legit-big"
        assert out["log"][0]["action"] == "none"

    def test_disabled_config_leaves_commands_alone(self) -> None:
        out = drive("run", {"config": {**OBSERVED, "enabled": False}, "calls": [{"id": "spin", "command": hot_loop(1)}]})
        spin = by_id(out, "spin")
        assert spin["exitCode"] == 0
        assert spin["rewritten"] is False
        assert "pi-guard" not in texts(spin)
        assert out["log"] == []
        assert "已禁用" in out["status"]

    def test_non_bash_tools_are_ignored(self) -> None:
        out = drive("run", {"config": OBSERVED, "calls": [{"id": "read", "toolName": "read", "command": "echo untouched"}]})
        assert by_id(out, "read")["content"] == ["untouched\n"]
        assert by_id(out, "read")["hookStructured"] is None
        assert out["log"] == []

    def test_guard_command_reports_thresholds(self) -> None:
        out = drive("run", {"config": OBSERVED, "calls": [{"id": "quiet", "command": "true"}]})
        status = out["status"]
        assert status.startswith("pi-guard:仅观测")
        assert "硬顶" in status
        assert "空转即停" in status
        assert "只记录不停" in status


class TestContainedDegrade:
    def test_wrap_failure_degrades_to_observed_and_tells_model_to_retry(self, tmp_path: Path) -> None:
        script = tmp_path / "fake-systemd-run"
        script.write_text(
            "#!/bin/sh\ncase \"$*\" in\n  *'cat /proc/self/cgroup'*) echo '0::/user.slice/user-1000.slice/user@1000.service/fake.slice/probe.scope'; exit 0;;\nesac\n"
            "echo 'Failed to connect to bus: No such file or directory' >&2\nexit 1\n"
        )
        script.chmod(0o755)
        root = tmp_path / "cgroup"
        slice_dir = root / "user.slice/user-1000.slice/user@1000.service/fake.slice"
        slice_dir.mkdir(parents=True)
        (root / "cgroup.controllers").write_text("memory pids\n")
        (slice_dir / "cgroup.procs").write_text("")
        (slice_dir / "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n")
        (slice_dir / "memory.max").write_text("max\n")
        (slice_dir / "memory.swap.max").write_text("max\n")
        spec = {
            "env": {"PI_GUARD_CGROUP_ROOT": str(root)},
            "config": {**OBSERVED, "systemdRun": str(script), "slice": "fake.slice", "sliceMaxBytes": 7 * 1024 * MB},
            "calls": [{"id": "first", "command": "echo hi"}, {"id": "second", "command": "echo again"}],
        }
        out = drive("run", spec)
        first = by_id(out, "first")
        assert first["rewritten"] is True
        assert "Failed to connect to bus" in texts(first)
        assert "[pi-guard] 隔离包装未能启动,已降级为仅观测模式;本条命令没有执行,请重试。" in texts(first)
        assert by_id(out, "second")["rewritten"] is False
        assert by_id(out, "second")["content"] == ["again\n"]
        assert "已降级" not in texts(by_id(out, "second"))
        assert out["status"].startswith("pi-guard:仅观测")
        assert (slice_dir / "memory.max").read_text().strip() == str(7 * 1024 * MB)
        assert (slice_dir / "memory.swap.max").read_text().strip() == "0"
