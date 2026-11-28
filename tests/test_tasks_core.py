import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "tasks_core_driver.mjs"


def drive(root: Path, scenario: str, payload: dict | None = None) -> dict:
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), str(root), scenario, json.dumps(payload or {}, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=dict(os.environ, HOME=str(home)),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_journal_replay_and_crash_recovery(tmp_path) -> None:
    created = drive(tmp_path, "create", {"cmd": "sleep 60", "name": "sleepy", "pid": 4194303})
    task_id = created["record"]["id"]
    assert created["record"]["state"] == "running"
    reloaded = drive(tmp_path, "reload")
    task = [t for t in reloaded["tasks"] if t["id"] == task_id][0]
    assert task["state"] == "exited"
    assert task["exitCode"] is None


def test_alive_pid_kept_running(tmp_path) -> None:
    proc = subprocess.Popen(["sleep", "6"])
    created = drive(tmp_path, "create", {"cmd": "sleep 6", "name": "alive", "pid": proc.pid})
    reloaded = drive(tmp_path, "reload")
    task = [t for t in reloaded["tasks"] if t["id"] == created["record"]["id"]][0]
    assert task["state"] == "running"
    proc.kill()
    proc.wait()


def test_exit_marking_idempotent_via_state(tmp_path) -> None:
    created = drive(tmp_path, "create", {"cmd": "true", "name": "quick", "pid": 4194303})
    task_id = created["record"]["id"]
    drive(tmp_path, "mark-exit", {"id": task_id, "exitCode": 3})
    listed = drive(tmp_path, "list")
    task = [t for t in listed["tasks"] if t["id"] == task_id][0]
    assert task["state"] == "exited"
    assert task["exitCode"] == 3
    drive(tmp_path, "mark-exit", {"id": task_id, "exitCode": 9})
    listed = drive(tmp_path, "list")
    task = [t for t in listed["tasks"] if t["id"] == task_id][0]
    assert task["exitCode"] == 3


def test_ring_buffer_cursor_survives_shrink(tmp_path) -> None:
    created = drive(tmp_path, "create", {"cmd": "log", "name": "logger", "pid": 4194303})
    task_id = created["record"]["id"]
    written = drive(tmp_path, "write-log", {"id": task_id, "kb": 300})
    assert written["bytes"] == 300 * 1024
    full = drive(tmp_path, "log-window", {"id": task_id, "since": 0})
    assert full["cursor"] == 300 * 1024
    assert full["contentLen"] == 16 * 1024 and full["skipped"] == 300 * 1024 - 16 * 1024
    shrunk = drive(tmp_path, "shrink", {"id": task_id})
    assert shrunk["logBase"] == 300 * 1024 - 128 * 1024
    after = drive(tmp_path, "log-window", {"id": task_id, "since": 0})
    assert after["cursor"] == 300 * 1024
    assert after["contentLen"] == 16 * 1024 and after["skipped"] == 128 * 1024 - 16 * 1024
    below_rotation = drive(tmp_path, "log-window", {"id": task_id, "since": 150 * 1024})
    assert below_rotation["contentLen"] == 16 * 1024 and below_rotation["skipped"] == 128 * 1024 - 16 * 1024
    tail = drive(tmp_path, "log-window", {"id": task_id, "since": 288 * 1024})
    assert tail["cursor"] == 300 * 1024
    assert tail["contentLen"] == 12 * 1024 and tail["skipped"] == 0


def test_gc_removes_expired_exited(tmp_path) -> None:
    drive(tmp_path, "create", {"cmd": "keep", "name": "fresh", "pid": 4194303})
    drive(tmp_path, "gc-prep")
    out = drive(tmp_path, "gc")
    assert out["removed"] >= 1
    assert "20000101000000-9" not in out["remaining"]
    assert out["logGone"] is True
    assert out["exitGone"] is True
    kinds = [json.loads(line)["kind"] for line in out["journal"].strip().split("\n") if line]
    assert "gc" in kinds


def test_cross_session_journal_exit_visible(tmp_path) -> None:
    out = drive(tmp_path, "cross-session-exit")
    assert out["state"] == "exited"
    assert out["exitCode"] == 7


def test_output_strips_terminal_control_codes(tmp_path) -> None:
    out = drive(tmp_path, "escape-filter")
    assert "\x1b" not in out["content"]
    assert "[" not in out["content"]
    assert "cleanred" in out["content"]
    assert "done" in out["content"]


def test_journal_offset_shortcircuit(tmp_path) -> None:
    out = drive(tmp_path, "offset-probe")
    assert out["offsetFirst"] == out["journalSize"]
    assert out["offsetSecondNoop"] == out["offsetFirst"]
    assert out["offsetFirst"] > 0


def test_forged_journal_events_dropped(tmp_path) -> None:
    out = drive(tmp_path, "forge-journal")
    assert out["names"] == []


def test_reap_owner_yield_takeover_self(tmp_path) -> None:
    out = drive(tmp_path, "reap-owner")
    assert out["selfState"] == "exited"
    assert out["deadOwnerState"] == "exited"
    assert out["yieldWhileOwnerAlive"] == "running"
    assert out["yieldAfterOwnerDeath"] == "exited"


def test_wait_until_three_modes_and_abort(tmp_path) -> None:
    instant = drive(tmp_path, "wait-until", {"mode": "instant"})
    assert instant["result"] == {"waitedMs": 0, "calls": 1}
    timeout = drive(tmp_path, "wait-until", {"mode": "timeout", "waitMs": 400, "intervalMs": 50})
    assert 390 <= timeout["result"]["waitedMs"] < 600 and timeout["result"]["calls"] >= 7
    flip = drive(tmp_path, "wait-until", {"mode": "flip", "delayMs": 250, "waitMs": 2000, "intervalMs": 50})
    assert 240 <= flip["result"]["waitedMs"] < 600
    abort = drive(tmp_path, "wait-until", {"mode": "abort", "abortAfterMs": 100, "waitMs": 2000, "intervalMs": 50})
    assert 90 <= abort["result"]["waitedMs"] < 400


def test_exit_recording_command(tmp_path) -> None:
    out = drive(tmp_path, "exit-command")
    assert out["plain"] == {"code": 7, "stdout": "hi\n", "file": "7"}
    assert out["quoted"]["code"] == 3 and out["quoted"]["file"] == "3"
    assert out["failed"]["code"] == 1 and out["failed"]["file"] == "1"
    assert out["trapKeepsStatus"] == {"code": 1, "stdout": "", "file": "1"}
    assert out["execed"]["code"] == 0 and out["execed"]["file"] is None


def test_exit_signal_survives_reload(tmp_path) -> None:
    out = drive(tmp_path, "exit-signal", {})
    assert out["reloadSignal"] == "SIGTERM"
    assert out["reloadCode"] is None
    assert out["text"] == "signal:SIGTERM"
    assert out["plausible"] is True


def test_orphan_detection_and_idempotent_mark(tmp_path) -> None:
    out = drive(tmp_path, "orphan", {})
    assert out["foreignWhileOwnerAlive"] == []
    assert out["ownExcluded"] == 0
    assert len(out["foreignAfterOwnerDeath"]) == 1
    assert out["orphanIds"] == out["foreignAfterOwnerDeath"]
    assert out["journalOrphanEvents"] == 1


def test_factory_fast_exit_observable_via_precheck(tmp_path) -> None:
    out = drive(tmp_path, "factory-e2e", {"cmd": "exit 42"})
    assert f"exit=code=42" in out["listText"]
    assert out["notifyText"] and "code=42" in out["notifyText"]


def test_factory_notify_steered_during_run_held_during_maintenance(tmp_path) -> None:
    out = drive(tmp_path, "factory-e2e", {"notifyPhases": True})
    run_id, maintenance_id = out["phaseIds"]
    assert out["runSentCount"] == 1 and run_id in out["runSentText"] and "code=3" in out["runSentText"]
    assert out["maintenanceSentCount"] == 0
    assert out["flushedSentCount"] == 1 and maintenance_id in out["flushedText"] and "code=4" in out["flushedText"]


def test_factory_notify_scoped_to_creating_session_not_subagent(tmp_path) -> None:
    out = drive(tmp_path / "reg", "factory-two-sessions")
    assert out["childSeesParentTask"] is True
    assert out["recordedExitCode"] == 7
    assert len(out["parentSent"]) == 1 and out["parentOwnedId"] in out["parentSent"][0] and "code=7" in out["parentSent"][0]
    assert out["childSent"] == []
    assert len(out["childOwnSent"]) == 1 and "code=9" in out["childOwnSent"][0]
    assert out["classifier"] == [True, True, False, False, False, False, False]


def test_factory_bg_task_flow(tmp_path) -> None:
    out = drive(tmp_path / "reg", "factory-bg-flow")
    assert out["runningState"] == "running" and out["running"].startswith("task:") and "flow" in out["running"]
    assert out["logCursor"] == 0 and out["logState"] == "running"
    assert out["waitedState"] == "exited" and out["waitedCode"] == 6 and out["waitedMs"] >= 900
    assert "exit=code=6" in out["waitedText"] and "FLOW_MARK" in out["finalText"] and "[cursor=10 state=exited exit=code=6]" in out["finalText"]
    assert out["againText"] == "(无输出)\n[cursor=10 state=exited exit=code=6]"
    assert "幂等跳过" in out["stopText"]
    assert out["badIsError"] is True and out["missingIsError"] is True
    assert out["listIsError"] is False and f"task:" in out["listText"]
    assert out["names"] == ["bg_list", "bg_log", "bg_schedule", "bg_status", "bg_stop", "task_create"]


def test_factory_bg_log_tail_and_cap(tmp_path) -> None:
    out = drive(tmp_path / "reg", "factory-bg-log-cap")
    assert out["state"] == "exited"
    assert out["tail"]["len"] == 4096 and out["tail"]["ends"] is True
    assert out["tail"]["protocol"] == "[cursor=20011 state=exited exit=code=0]"
    assert out["full"]["len"] == 16 * 1024 and "省略=3627字节" in out["full"]["protocol"]
    assert out["again"] == "(无输出)\n[cursor=20011 state=exited exit=code=0]"


def test_factory_exit_code_survives_instance_loss(tmp_path) -> None:
    out = drive(tmp_path / "reg", "factory-reload-exit-code")
    assert out["state"] == "exited" and out["code"] == 7 and "exit=code=7" in out["text"]
    assert out["journalCode"] == 7 and "exit=code=7" in out["listed"]
