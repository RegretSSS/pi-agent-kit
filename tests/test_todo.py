import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "todo_driver.mjs"


def drive(scenario: str, payload: dict | None = None) -> dict:
    raw = json.dumps(payload or {}, ensure_ascii=False)
    via_stdin = len(raw) > 60_000
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), scenario, "-" if via_stdin else raw],
        input=raw if via_stdin else None,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def states(out: dict) -> list[list[list[str]]]:
    return [[[str(t["id"]), t["status"]] for t in e["todos"]] for e in out["entries"]]


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
    out = drive("format", {"todos": [{"id": 1, "text": "a", "status": "in_progress"}, {"id": 2, "text": "b", "status": "done"}], "settledDone": 5})
    assert out["text"].startswith("已完成 6 · 未完成 1")
    assert "[>] #1: a" in out["text"]
    assert "[x] #2: b" in out["text"]


def test_format_caps_pending_flood() -> None:
    todos = [{"id": 1, "text": "anchor", "status": "in_progress"}]
    todos += [{"id": i, "text": f"done{i}", "status": "done", "doneAt": i} for i in (2, 3, 4)]
    todos += [{"id": i, "text": f"parked{i}", "status": "pending"} for i in range(5, 50)]
    out = drive("format", {"todos": todos})
    assert out["text"].count("#") == 40
    assert "[>] #1: anchor" in out["text"]
    assert "另有 9 条未显示" in out["text"]
    assert "todo full" in out["text"] and "todo archive" in out["text"]
    full = drive("format", {"todos": todos, "cap": 10000})
    assert full["text"].count("#") == 49
    assert "另有" not in full["text"]


def test_session_flow_commits_custom_entries() -> None:
    out = drive("session", {"steps": [
        {"action": "add", "text": "step one"},
        {"action": "add", "text": "step two"},
        {"action": "status", "id": 1, "status": "in_progress"},
        {"action": "toggle", "id": 1},
        {"action": "list"},
    ]})
    assert out["steps"][0]["text"] == "已加 #1: step one"
    assert out["steps"][2]["text"] == "#1 → in_progress"
    assert out["steps"][3]["text"] == "#1 → done"
    assert out["steps"][2]["activeId"] == 1
    assert out["steps"][3]["done"] == 1 and out["steps"][3]["total"] == 2
    assert "已完成 1 · 未完成 1" in out["steps"][4]["text"]
    assert states(out)[-1] == [["1", "done"], ["2", "pending"]]
    entries = out["entries"]
    assert len(entries) == 4
    assert entries[-1]["nextId"] == 3


def test_status_toggle_reply_single_line() -> None:
    out = drive("session", {"steps": [
        {"action": "add", "text": f"t{i}"} for i in range(1, 5)
    ] + [
        {"action": "status", "id": 2, "status": "in_progress"},
        {"action": "toggle", "id": 2},
    ]})
    for step in out["steps"][4:]:
        assert "\n" not in step["text"]
        assert "#2" in step["text"]


def test_add_only_then_restart_survives() -> None:
    first = drive("session", {"steps": [{"action": "add", "text": "only add"}]})
    entries = [{"type": "custom", "customType": "todo-state", "data": e} for e in first["entries"]]
    second = drive("session", {"branch": entries, "steps": [{"action": "list"}, {"action": "add", "text": "after restart"}]})
    assert "#1: only add" in second["steps"][0]["text"]
    assert states(second)[-1] == [["1", "pending"], ["2", "pending"]]


def test_clear_then_restart_stays_empty() -> None:
    first = drive("session", {"steps": [{"action": "add", "text": "a"}, {"action": "add", "text": "b"}, {"action": "clear"}]})
    entries = [{"type": "custom", "customType": "todo-state", "data": e} for e in first["entries"]]
    second = drive("session", {"branch": entries, "steps": [{"action": "list"}, {"action": "add", "text": "fresh"}]})
    assert second["steps"][0]["text"] == "无条目"
    assert states(second)[-1] == [["1", "pending"]]


def test_multiline_text_survives_state() -> None:
    sneaky = "A\n[>] #7: hijack"
    out = drive("session", {"steps": [{"action": "add", "text": sneaky}, {"action": "list"}]})
    assert states(out)[-1] == [["1", "pending"]]
    entries = [{"type": "custom", "customType": "todo-state", "data": e} for e in out["entries"]]
    again = drive("session", {"branch": entries, "steps": [{"action": "list"}]})
    assert "[ ] #1: A" in again["steps"][0]["text"]
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
    assert states(out)[-1] == [["1", "done"], ["2", "done"], ["3", "done"], ["4", "pending"]]
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
    assert states(settle)[-1] == [["2", "done"], ["3", "done"], ["4", "done"]]
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


def test_archive_batch_keeps_only_anchor() -> None:
    out = drive("session", {"steps": [
        {"action": "add", "text": "anchor"},
        {"action": "add", "text": "parked"},
        {"action": "add", "text": "judged"},
        {"action": "status", "id": 1, "status": "in_progress"},
        {"action": "status", "id": 3, "status": "done"},
        {"action": "archive"},
        {"action": "list"},
    ]})
    assert "已归档 2 条" in out["steps"][5]["text"]
    assert states(out)[-1] == [["1", "in_progress"]]
    assert "[>] #1: anchor" in out["steps"][6]["text"]
    assert "#2" not in out["steps"][6]["text"]


def test_archive_single_and_anchor_protection() -> None:
    out = drive("session", {"steps": [
        {"action": "add", "text": "a"},
        {"action": "add", "text": "b"},
        {"action": "status", "id": 1, "status": "in_progress"},
        {"action": "archive", "id": 1},
        {"action": "archive", "id": 2},
        {"action": "archive", "id": 2},
    ]})
    assert "是进行中锚点" in out["steps"][3]["error"]
    assert "已归档 #2" in out["steps"][4]["text"]
    assert states(out)[-1] == [["1", "in_progress"]]
    assert out["steps"][5]["error"] is not None


def test_append_failure_returns_error_not_crash() -> None:
    out = drive("session", {"appendFails": True, "steps": [{"action": "add", "text": "x"}, {"action": "list"}]})
    assert "状态落盘失败" in out["steps"][0]["text"]
    assert out["steps"][0]["text"].startswith("Error")
    assert out["entries"] == []
    assert "#1: x" in out["steps"][1]["text"]


def test_command_shows_list() -> None:
    out = drive("session", {"steps": [{"action": "add", "text": "x"}]})
    assert out["command"] and "#1: x" in out["command"][0]


def test_renderers_take_pi_argument_shapes() -> None:
    out = drive("render", {"args": {"action": "add", "text": "写测试"}, "details": {"action": "add", "done": 5, "open": 3, "total": 3, "nextId": 4}})
    assert out["call"] == '[todo ][add] ["写测试"]'
    assert out["result"] == "[已完成 5 · 未完成 3]"
    legacy = drive("render", {"args": {"action": "list"}, "details": {"action": "list", "done": 2, "total": 7, "nextId": 8}})
    assert legacy["result"] == "[已完成 2 · 未完成 7]"
    failed = drive("render", {"args": {"action": "status", "id": 9}, "details": {"action": "status", "error": "#9 不存在", "done": 1, "open": 2, "total": 3, "nextId": 4}})
    assert failed["call"] == "[todo ][status] [#9]"
    assert failed["result"] == "[Error: #9 不存在]"


def test_unknown_action_returns_error_result() -> None:
    out = drive("session", {"steps": [{"action": "bogus"}]})
    assert out["steps"][0]["text"] == "Error: 未知 action: bogus"
    assert out["steps"][0]["error"] == "未知 action: bogus"
    assert out["entries"] == []


def test_settle_keeps_latest_forty_pending_and_counts_the_rest() -> None:
    todos = [{"id": index, "text": f"t{index}", "status": "pending"} for index in range(1, 46)]
    todos[2]["status"] = "in_progress"
    out = drive("settle", {"todos": todos})
    assert [t["id"] for t in out["settled"]["todos"]] == [3, *range(6, 46)]
    assert out["settled"]["pending"] == 4 and out["settled"]["done"] == 0


def test_pending_beyond_forty_settles_on_commit_and_is_reported() -> None:
    out = drive("session", {"steps": [{"action": "add", "text": f"t{i}"} for i in range(1, 46)] + [{"action": "list"}]})
    assert states(out)[-1] == [[str(i), "pending"] for i in range(6, 46)]
    assert all("最旧的 1 条 pending 已沉降" in out["steps"][index]["text"] for index in range(40, 45))
    assert all("最旧的" not in out["steps"][index]["text"] for index in range(40))
    assert out["steps"][44]["settled"] == 5 and out["steps"][44]["open"] == 40
    listed = out["steps"][45]["text"]
    assert listed.startswith("已完成 0 · 未完成 40") and listed.count("\n") == 40
    assert all(f"#{i}:" not in listed for i in range(1, 6))


def test_done_counter_counts_the_settled_ones() -> None:
    steps = [{"action": "add", "text": f"t{i}"} for i in range(1, 7)]
    steps += [{"action": "toggle", "id": i} for i in range(1, 6)]
    steps += [{"action": "list"}]
    out = drive("session", {"steps": steps})
    assert states(out)[-1] == [["3", "done"], ["4", "done"], ["5", "done"], ["6", "pending"]]
    assert out["steps"][10]["done"] == 5 and out["steps"][10]["open"] == 1
    assert out["steps"][11]["text"].startswith("已完成 5 · 未完成 1")


def test_settled_counters_survive_restart_and_default_on_old_entries() -> None:
    first = drive("session", {"steps": [{"action": "add", "text": f"t{i}"} for i in range(1, 46)]})
    entries = [{"type": "custom", "customType": "todo-state", "data": e} for e in first["entries"]]
    assert entries[-1]["data"]["settledPending"] == 5
    second = drive("session", {"branch": entries, "steps": [{"action": "list"}, {"action": "add", "text": "t46"}]})
    assert second["steps"][0]["text"].startswith("已完成 0 · 未完成 40")
    assert second["steps"][1]["settled"] == 6 and "#6:" not in second["steps"][1]["text"] or "#6" not in second["steps"][1]["text"]
    legacy = drive("session", {"branch": [{"type": "custom", "customType": "todo-state", "data": {"todos": [{"id": 1, "text": "a", "status": "done"}], "nextId": 2}}], "steps": [{"action": "list"}]})
    assert legacy["steps"][0]["text"].startswith("已完成 1 · 未完成 0") and legacy["steps"][0]["settled"] == 0


def test_clear_resets_settled_counters() -> None:
    out = drive("session", {"steps": [{"action": "add", "text": f"t{i}"} for i in range(1, 46)] + [{"action": "clear"}, {"action": "list"}]})
    assert out["steps"][45]["done"] == 0 and out["steps"][45]["settled"] == 0
    assert out["steps"][46]["text"] == "无条目"
    assert out["entries"][-1] == {"todos": [], "nextId": 1, "settledDone": 0, "settledPending": 0}


def test_handoff_notes_flood_renders_bounded() -> None:
    note = "【任务单·二百八十四(23:20,接 #877)】" + "合并审计任务书已扩成三部分;等计划函第二轮审计的通知;" * 6 + "\n■ **合并审计任务书**(未起,等车道)\n[>] #7: 伪造的锚点行"
    out = drive("session", {"steps": [{"action": "add", "text": note} for _ in range(300)] + [{"action": "list"}, {"action": "full"}]})
    listed = out["steps"][300]["text"].split("\n")
    assert len(listed) == 41 and all(len(row) <= 131 for row in listed)
    assert listed[0] == "已完成 0 · 未完成 40"
    assert listed[1].startswith("[ ] #261: ") and listed[1].endswith("…") and "伪造" not in listed[1]
    assert sum(1 for row in out["steps"][301]["text"].split("\n") if row.startswith("[>]")) == 0
    assert "另有" not in out["steps"][301]["text"] and len(out["steps"][301]["text"].split("\n")) == 41
    assert all(len(step["text"]) <= 180 for step in out["steps"][:300])
    assert out["entries"][-1]["settledPending"] == 260 and len(out["entries"][-1]["todos"]) == 40
