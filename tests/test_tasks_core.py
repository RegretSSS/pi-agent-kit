import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "tasks_core_driver.mjs"


def drive(root: Path, scenario: str, payload: dict | None = None) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), str(root), scenario, json.dumps(payload or {}, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
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
    full = drive(tmp_path, "read-range", {"id": task_id, "since": 0})
    assert full["cursor"] == 300 * 1024
    assert full["contentLen"] == 300 * 1024
    mid_cursor = 150 * 1024
    half = drive(tmp_path, "read-range", {"id": task_id, "since": mid_cursor})
    assert half["cursor"] == 300 * 1024
    assert half["contentLen"] == 150 * 1024
    shrunk = drive(tmp_path, "shrink", {"id": task_id})
    assert shrunk["logBase"] == 300 * 1024 - 128 * 1024
    after = drive(tmp_path, "read-range", {"id": task_id, "since": 0})
    assert after["cursor"] == 300 * 1024
    assert after["contentLen"] == 128 * 1024
    tail = drive(tmp_path, "read-range", {"id": task_id, "since": mid_cursor})
    assert tail["cursor"] == 300 * 1024
    assert tail["contentLen"] == 128 * 1024 - 0


def test_gc_removes_expired_exited(tmp_path) -> None:
    drive(tmp_path, "create", {"cmd": "keep", "name": "fresh", "pid": 4194303})
    drive(tmp_path, "gc-prep")
    out = drive(tmp_path, "gc")
    assert out["removed"] >= 1
    assert "20000101000000-9" not in out["remaining"]
    assert out["logGone"] is True
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


def test_poll_for_progress_three_modes(tmp_path) -> None:
    instant = drive(tmp_path, "poll-progress", {"mode": "instant"})
    assert instant["result"]["changed"] is True and instant["result"]["waitedMs"] == 0
    timeout = drive(tmp_path, "poll-progress", {"mode": "timeout", "waitMs": 400, "intervalMs": 50})
    assert timeout["result"]["changed"] is False and timeout["result"]["waitedMs"] >= 350
    grow = drive(tmp_path, "poll-progress", {"mode": "grow", "delayMs": 250, "waitMs": 2000, "intervalMs": 50})
    assert grow["result"]["changed"] is True and 200 <= grow["result"]["waitedMs"] < 1500
    exited = drive(tmp_path, "poll-progress", {"mode": "exit", "delayMs": 250, "waitMs": 2000, "intervalMs": 50})
    assert exited["result"]["changed"] is True and exited["result"]["state"] == "exited" and exited["result"]["cursor"] == 10


def test_output_wait_real_log_growth(tmp_path) -> None:
    out = drive(tmp_path, "output-wait", {"appendAfterMs": 300, "appendText": "watcher-woken", "waitMs": 3000})
    assert out["result"]["changed"] is True
    assert out["result"]["content"] == "watcher-woken"
    assert out["result"]["elapsedMs"] >= 250
    quiet = drive(tmp_path, "output-wait", {"waitMs": 400})
    assert quiet["result"]["changed"] is False and quiet["result"]["content"] == ""
