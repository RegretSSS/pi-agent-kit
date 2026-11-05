import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "subagent_jobs_driver.mjs"

JOB = {
    "id": "W6E5_nfAyQ",
    "name": "每日晨报巡查agent",
    "schedule": "2026-11-06T00:00:00.000Z",
    "scheduleType": "once",
    "enabled": True,
    "runCount": 0,
    "createdAt": "2026-11-05T01:20:57.300Z",
}


def drive(scenario: str, payload: dict) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), scenario, json.dumps(payload, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_format_empty_and_rows() -> None:
    assert drive("format", {"jobs": []})["text"] == "无定时任务"
    text = drive("format", {"jobs": [JOB]})["text"]
    assert "共 1 个定时任务" in text
    assert "- W6E5_nfAyQ | 每日晨报巡查agent | once 2026-11-06T00:00:00.000Z | enabled | 已跑 0 次" in text
    assert "重启不丢" in text
    assert "/agents" in text


def test_list_reads_store(tmp_path) -> None:
    store = tmp_path / ".pi" / "subagent-schedules"
    store.mkdir(parents=True)
    (store / "sess-1.json").write_text(json.dumps({"version": 1, "jobs": [JOB]}), encoding="utf8")
    outcome = drive("list", {"cwd": str(tmp_path), "sessionId": "sess-1"})["outcome"]
    assert outcome["status"] == "ok"
    assert "- W6E5_nfAyQ |" in outcome["text"]
    assert outcome["jobs"][0] == {"id": "W6E5_nfAyQ", "name": "每日晨报巡查agent", "enabled": True, "scheduleType": "once", "schedule": "2026-11-06T00:00:00.000Z"}


def test_list_missing_store_means_no_jobs(tmp_path) -> None:
    assert drive("list", {"cwd": str(tmp_path), "sessionId": "sess-1"})["outcome"]["status"] == "no-store"


def test_list_corrupt_store_is_unreadable(tmp_path) -> None:
    store = tmp_path / ".pi" / "subagent-schedules"
    store.mkdir(parents=True)
    (store / "sess-1.json").write_text("{broken", encoding="utf8")
    outcome = drive("list", {"cwd": str(tmp_path), "sessionId": "sess-1"})["outcome"]
    assert outcome["status"] == "unreadable"


def test_list_without_session_id(tmp_path) -> None:
    assert drive("list", {"cwd": str(tmp_path), "noSessionId": True})["outcome"]["status"] == "no-session"


def test_store_path_layout() -> None:
    assert drive("path", {"cwd": "/w", "sessionId": "s"})["path"] == "/w/.pi/subagent-schedules/s.json"
