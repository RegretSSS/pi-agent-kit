import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "todo_driver.mjs"


def drive(scenario: str, payload: dict | None = None) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), scenario, json.dumps(payload or {}, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_in_progress_single_anchor() -> None:
    todos = [
        {"id": 1, "text": "a", "status": "in_progress"},
        {"id": 2, "text": "b", "status": "pending"},
    ]
    out = drive("mark-status", {"todos": todos, "id": 2, "status": "in_progress"})
    by_id = {t["id"]: t["status"] for t in out["todos"]}
    assert by_id == {1: "pending", 2: "in_progress"}


def test_mark_status_missing_id_noop() -> None:
    todos = [{"id": 1, "text": "a", "status": "pending"}]
    out = drive("mark-status", {"todos": todos, "id": 9, "status": "done"})
    assert out["todos"] == todos


def test_reconstruct_replays_latest_custom_entry() -> None:
    branch = [
        {"type": "custom", "customType": "todo-state", "data": {"todos": [{"id": 1, "text": "a", "status": "pending"}], "nextId": 2}},
        {"type": "custom", "customType": "other-ext", "data": {"todos": [], "nextId": 99}},
        {"type": "custom", "customType": "todo-state", "data": {"todos": [{"id": 1, "text": "a", "status": "done"}, {"id": 2, "text": "b", "status": "in_progress"}], "nextId": 3}},
    ]
    out = drive("reconstruct", {"branch": branch})
    assert out["state"]["nextId"] == 3
    assert {t["id"]: t["status"] for t in out["state"]["todos"]} == {1: "done", 2: "in_progress"}


def test_reconstruct_empty_branch_starts_blank() -> None:
    out = drive("reconstruct", {"branch": []})
    assert out["state"] == {"todos": [], "nextId": 1}


def test_format_marks_active() -> None:
    out = drive("format", {"todos": [{"id": 1, "text": "a", "status": "in_progress"}, {"id": 2, "text": "b", "status": "done"}]})
    assert "1/2 完成" in out["text"]
    assert "[>] #1: a" in out["text"]
    assert "[x] #2: b" in out["text"]


def test_session_flow_commits_custom_entries() -> None:
    out = drive("session", {"steps": [
        {"action": "add", "text": "step one"},
        {"action": "add", "text": "step two"},
        {"action": "status", "id": 1, "status": "in_progress"},
        {"action": "toggle", "id": 1},
        {"action": "list"},
    ]})
    assert out["steps"][0]["text"] == "已加 #1: step one"
    assert out["steps"][2]["todos"] == [["1", "in_progress"], ["2", "pending"]]
    assert out["steps"][3]["todos"] == [["1", "done"], ["2", "pending"]]
    assert "1/2 完成" in out["steps"][4]["text"]
    entries = out["entries"]
    assert len(entries) == 4
    assert entries[-1]["nextId"] == 3
    assert {t["id"]: t["status"] for t in entries[-1]["todos"]} == {1: "done", 2: "pending"}


def test_add_only_then_restart_survives() -> None:
    first = drive("session", {"steps": [{"action": "add", "text": "only add"}]})
    entries = [{"type": "custom", "customType": "todo-state", "data": e} for e in first["entries"]]
    second = drive("session", {"branch": entries, "steps": [{"action": "list"}, {"action": "add", "text": "after restart"}]})
    assert "#1: only add" in second["steps"][0]["text"]
    assert second["steps"][1]["todos"] == [["1", "pending"], ["2", "pending"]]


def test_clear_then_restart_stays_empty() -> None:
    first = drive("session", {"steps": [{"action": "add", "text": "a"}, {"action": "add", "text": "b"}, {"action": "clear"}]})
    entries = [{"type": "custom", "customType": "todo-state", "data": e} for e in first["entries"]]
    second = drive("session", {"branch": entries, "steps": [{"action": "list"}, {"action": "add", "text": "fresh"}]})
    assert second["steps"][0]["text"] == "无条目"
    assert second["steps"][1]["todos"] == [["1", "pending"]]


def test_multiline_text_survives_state() -> None:
    sneaky = "A\n[>] #7: hijack"
    out = drive("session", {"steps": [{"action": "add", "text": sneaky}, {"action": "list"}]})
    assert out["steps"][0]["todos"] == [["1", "pending"]]
    entries = [{"type": "custom", "customType": "todo-state", "data": e} for e in out["entries"]]
    again = drive("session", {"branch": entries, "steps": [{"action": "list"}]})
    assert again["steps"][0]["todos"] == [["1", "pending"]]
    assert out["entries"][0]["todos"][0]["text"] == sneaky


def test_done_settles_beyond_keep_three() -> None:
    out = drive("session", {"steps": [
        {"action": "add", "text": "t1"},
        {"action": "add", "text": "t2"},
        {"action": "add", "text": "t3"},
        {"action": "add", "text": "t4"},
        {"action": "toggle", "id": 1},
        {"action": "toggle", "id": 2},
        {"action": "toggle", "id": 3},
        {"action": "list"},
    ]})
    assert out["steps"][7]["todos"] == [["1", "done"], ["2", "done"], ["3", "done"], ["4", "pending"]]
    settle = drive("session", {"steps": [
        {"action": "add", "text": "t1"},
        {"action": "add", "text": "t2"},
        {"action": "add", "text": "t3"},
        {"action": "add", "text": "t4"},
        {"action": "toggle", "id": 1},
        {"action": "toggle", "id": 2},
        {"action": "toggle", "id": 3},
        {"action": "toggle", "id": 4},
        {"action": "list"},
    ]})
    assert settle["steps"][8]["todos"] == [["2", "done"], ["3", "done"], ["4", "done"]]
    assert settle["steps"][8]["text"].count("#1:") == 0


def test_settled_history_still_in_journal() -> None:
    first = drive("session", {"steps": [
        {"action": "add", "text": "old"},
        {"action": "add", "text": "keep-a"},
        {"action": "add", "text": "keep-b"},
        {"action": "add", "text": "keep-c"},
        {"action": "toggle", "id": 1},
        {"action": "toggle", "id": 2},
        {"action": "toggle", "id": 3},
        {"action": "toggle", "id": 4},
    ]})
    settled = [e for e in first["entries"] if not any(t["id"] == 1 for t in e["todos"])]
    assert any(any(t["id"] == 1 for t in e["todos"]) for e in first["entries"][:-1])
    assert all(not any(t["id"] == 1 for t in e["todos"]) for e in settled[-1:])
    grep_like = [t for e in first["entries"] for t in e["todos"] if t["id"] == 1]
    assert grep_like, "沉降后旧条目仍应能在 journal 历史快照里 grep 到"


def test_command_shows_list() -> None:
    out = drive("session", {"steps": [{"action": "add", "text": "x"}]})
    assert out["command"] and "#1: x" in out["command"][0]
