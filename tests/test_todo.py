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


def test_reconstruct_falls_back_to_content_text() -> None:
    branch = [
        {"type": "message", "message": {"role": "toolResult", "toolName": "todo", "content": [{"type": "text", "text": "0/2 完成\n[ ] #1: first\n[>] #2: second ← 进行中"}]}},
        {"type": "message", "message": {"role": "toolResult", "toolName": "todo", "content": [{"type": "text", "text": "1/2 完成\n[x] #1: first\n[>] #2: second ← 进行中"}]}},
    ]
    out = drive("reconstruct", {"branch": branch})
    assert out["state"]["nextId"] == 3
    assert {t["id"]: t["status"] for t in out["state"]["todos"]} == {1: "done", 2: "in_progress"}


def test_parse_todos_roundtrip() -> None:
    todos = [
        {"id": 1, "text": "扫描全部文件", "status": "pending"},
        {"id": 2, "text": "修 lint", "status": "in_progress"},
        {"id": 3, "text": "提交", "status": "done"},
    ]
    text = drive("format", {"todos": todos})["text"]
    out = drive("reconstruct", {"branch": [
        {"type": "message", "message": {"role": "toolResult", "toolName": "todo", "content": [{"type": "text", "text": text}]}},
    ]})
    assert {t["id"]: (t["status"], t["text"]) for t in out["state"]["todos"]} == {1: ("pending", "扫描全部文件"), 2: ("in_progress", "修 lint"), 3: ("done", "提交")}


def test_reconstruct_replays_latest_details() -> None:
    branch = [
        {"type": "message", "message": {"role": "toolResult", "toolName": "todo", "details": {"todos": [{"id": 1, "text": "a", "status": "pending"}], "nextId": 2}}},
        {"type": "message", "message": {"role": "toolResult", "toolName": "other", "details": {"todos": [], "nextId": 1}}},
        {"type": "message", "message": {"role": "toolResult", "toolName": "todo", "details": {"todos": [{"id": 1, "text": "a", "status": "done"}, {"id": 2, "text": "b", "status": "in_progress"}], "nextId": 3}}},
    ]
    out = drive("reconstruct", {"branch": branch})
    assert out["state"]["nextId"] == 3
    assert {t["id"]: t["status"] for t in out["state"]["todos"]} == {1: "done", 2: "in_progress"}


def test_format_marks_active() -> None:
    out = drive("format", {"todos": [{"id": 1, "text": "a", "status": "in_progress"}, {"id": 2, "text": "b", "status": "done"}]})
    assert "1/2 完成" in out["text"]
    assert "[>] #1: a ← 进行中" in out["text"]
    assert "[x] #2: b" in out["text"]


def test_session_flow_add_status_toggle_clear() -> None:
    out = drive("session", {"steps": [
        {"action": "add", "text": "step one"},
        {"action": "add", "text": "step two"},
        {"action": "status", "id": 1, "status": "in_progress"},
        {"action": "toggle", "id": 1},
        {"action": "list"},
    ]})
    assert out["steps"][0]["text"] == "已加 #1: step one"
    assert out["steps"][2]["todos"] == ["1:in_progress", "2:pending"]
    assert out["steps"][3]["todos"] == ["1:done", "2:pending"]
    assert "1/2 完成" in out["steps"][4]["text"]


def test_session_reconstruct_then_add_keeps_ids() -> None:
    branch = [
        {"type": "message", "message": {"role": "toolResult", "toolName": "todo", "details": {"todos": [{"id": 1, "text": "a", "status": "done"}], "nextId": 2}}},
    ]
    out = drive("session", {"branch": branch, "steps": [{"action": "add", "text": "b"}]})
    assert out["steps"][0]["todos"] == ["1:done", "2:pending"]


def test_command_shows_list() -> None:
    out = drive("session", {"steps": [{"action": "add", "text": "x"}]})
    assert out["command"] and "已加" not in out["command"][0]
    assert "#1: x" in out["command"][0]
