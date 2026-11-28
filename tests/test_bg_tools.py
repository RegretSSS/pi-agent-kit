import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "bg_tools_driver.mjs"

JOB = {
    "id": "W6E5_nfAyQ",
    "name": "每日晨报巡查agent",
    "schedule": "2026-11-06T00:00:00.000Z",
    "scheduleType": "once",
    "enabled": True,
    "runCount": 0,
    "createdAt": "2026-11-05T01:20:57.300Z",
    "nextRun": "2026-11-06T00:00:00.000Z",
}

RUN = {
    "id": "wf_abc123def456",
    "name": "hub-log-watch",
    "status": "running",
    "doneCount": 2,
    "agentCount": 5,
    "replayedCount": 0,
    "tokens": 1234,
    "toolCalls": 30,
    "logCount": 3,
    "startedAt": 1762300000000,
    "scriptPath": "/s/template.js",
    "journalPath": "/s/journal.jsonl",
}

STATUS_DETAIL = dict(
    RUN,
    logs=["守窗第 1 轮", "安静,推进偏移"],
    agents=[
        {"label": "watch", "state": "done", "tokens": 800},
        {"label": "watch", "state": "error", "error": "rpc timeout"},
    ],
)

AGENT_RUNNING = {"id": "agent-run1", "type": "general-purpose", "description": "巡查 hub 日志", "status": "running", "depth": 1, "handle": "watcher", "startedAt": 1762300000000, "durationMs": 45000, "toolUses": 3, "tokens": {"input": 100, "output": 20, "total": 120}}
AGENT_DONE = {"id": "agent-run1", "type": "general-purpose", "description": "巡查 hub 日志", "status": "completed", "depth": 1, "handle": "watcher", "startedAt": 1762300000000, "completedAt": 1762300004000, "durationMs": 4000, "toolUses": 9, "result": "逐行核对完毕,结论:全部通过,无需跟进。" * 20}
AGENT_ERROR = {"id": "agent-err1", "type": "general-purpose", "description": "判官", "status": "error", "depth": 2, "workflowId": "wf_abc123def456", "startedAt": 1762300000000, "durationMs": 900, "toolUses": 0, "error": "model timeout after 3 retries"}
NO_LIST = ["consume", "steer", "get", "kit-workflow", "kit-schedule"]
NO_KIT = ["consume", "steer", "get", "list"]


def drive(root: Path, scenario: str, payload: dict) -> dict:
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), str(root), scenario, json.dumps(payload, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=dict(os.environ, HOME=str(home)),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def tools(payload: dict, root: Path) -> list[dict]:
    return drive(root, "tools", payload)["results"]


def test_handle_forms(tmp_path) -> None:
    out = drive(tmp_path, "format", {"handles": ["task:20261128090000-1-abcd", "agent:@watcher", "wf:wf_abc", "job:W6E5", " agent: id1 ", "task:", "foo:x", "20261128090000-1-abcd"]})["handles"]
    assert out[0] == {"kind": "task", "key": "20261128090000-1-abcd"}
    assert out[1] == {"kind": "agent", "key": "@watcher"}
    assert out[2] == {"kind": "wf", "key": "wf_abc"} and out[3] == {"kind": "job", "key": "W6E5"}
    assert out[4] == {"kind": "agent", "key": "id1"}
    assert out[5:] == [None, None, None]


def test_rows_carry_handles(tmp_path) -> None:
    base = {"exitCode": None, "logBase": 0, "created": "2026-11-28T09:00:00.000Z"}
    out = drive(tmp_path, "format", {
        "task": dict(base, id="20261128090000-1-abcd", name="构建", pid=4321, state="running"),
        "agent": AGENT_RUNNING,
        "workflow": RUN,
        "statusDetail": STATUS_DETAIL,
        "job": JOB,
    })
    assert out["task"] == "task:20261128090000-1-abcd | running | pid=4321 | owner=? | 构建"
    assert out["agent"] == "agent:agent-run1 @watcher | running | general-purpose | tokens 120 | tools 3 | 45s | 巡查 hub 日志"
    assert out["workflow"] == "wf:wf_abc123def456 | hub-log-watch | running | agents 2/5 | tokens 1234 | 2025-11-04T23:46:40.000Z"
    assert out["statusLines"][0].startswith("wf:wf_abc123def456 | hub-log-watch | running")
    status = "\n".join(out["statusLines"])
    assert "script: /s/template.js" in status and "journal: /s/journal.jsonl" in status
    assert "[done] tokens 800" in status and "[error] | rpc timeout" in status and "安静,推进偏移" in status
    assert out["job"] == "job:W6E5_nfAyQ | 每日晨报巡查agent | once 2026-11-06T00:00:00.000Z | enabled | 已跑 0 次 | 下次 2026-11-06T00:00:00.000Z"
    orphan = drive(tmp_path, "format", {"task": dict(base, id="20261128090000-2-abcd", name="旧", pid=4321, state="exited", exitCode=None, orphanAt="x", ownerPid=999)})["task"]
    assert orphan == "task:20261128090000-2-abcd | exited | pid=4321 | owner=999 [orphan] | exit=unknown(reaped,无退出观测) | 旧"
    error = drive(tmp_path, "format", {"agent": AGENT_ERROR})["agent"]
    assert "agent:agent-err1 | error | general-purpose | wf:wf_abc123def456" in error and "判官" in error


def test_transcript_row_summary(tmp_path) -> None:
    messages = [
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "sleep 1"}}]},
        {"role": "assistant", "content": [{"type": "text", "text": "全部\n 完成"}]},
        {"role": "toolResult", "toolName": "bash", "content": [{"type": "text", "text": "ok"}]},
        {"role": "toolResult", "toolName": "read", "isError": True, "content": "missing"},
        {"role": "system", "content": ""},
        {"role": "assistant", "content": []},
    ]
    out = drive(tmp_path, "format", {"messages": messages, "text": "x" * 50, "chars": 10})
    assert out["transcript"][:4] == ['[bash] {"command":"sleep 1"}', "全部 完成", "[result bash] ok", "[result read ERROR] missing"]
    assert out["transcript"][4:] == [None, None]
    assert out["head"] == "xxxxxxxxxx…" and out["tail"] == "xxxxxxxxxx"


def test_log_windows_are_indexed(tmp_path) -> None:
    out = drive(tmp_path, "log-windows", {"rows": [{"index": 5, "ok": True, "text": "a"}, {"index": 9, "ok": False, "text": "b"}], "since": 9})
    assert out["journal"] == {"lines": ["9 FAILED b"], "cursor": 10}
    plain = drive(tmp_path, "log-windows", {"logs": ["一", "二", "三"], "logTotal": 8, "since": 6})
    assert plain["workflow"] == {"lines": ["6 二", "7 三"], "cursor": 8} and plain["journal"] is None
    fresh = drive(tmp_path, "log-windows", {"rows": [{"index": 0, "ok": True, "text": "一"}, {"index": 1, "ok": True, "text": "二"}], "logs": ["一", "二"], "logTotal": 2})
    assert fresh["workflow"]["lines"] == ["0 一", "1 二"] and fresh["journal"] == {"lines": ["0 ok 一", "1 ok 二"], "cursor": 2}


def test_transcript_window_tail_and_incremental(tmp_path) -> None:
    entries = [{"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": f"第 {n} 步"}]}} for n in range(20)]
    out = drive(tmp_path, "transcript-window", {"make": entries, "fresh": True, "partial": False})
    assert len(out["window"]["rows"]) == 12 and out["window"]["rows"][0] == "第 8 步" and out["window"]["rows"][-1] == "第 19 步"
    size = out["window"]["cursor"]
    again = drive(tmp_path, "transcript-window", {"since": size})
    assert again["window"]["rows"] == [] and again["window"]["cursor"] == size
    grown = drive(tmp_path, "transcript-window", {"make": entries + [{"type": "message", "message": {"role": "assistant", "content": "新增"}}], "since": size})
    assert grown["window"]["rows"] == ["新增"]
    partial = drive(tmp_path, "transcript-window", {"make": entries[:2], "fresh": True, "partial": True})
    assert len(partial["window"]["rows"]) == 1 and partial["missing"] is None


def test_schedule_rpc_ok_and_timeout(tmp_path) -> None:
    ok = drive(tmp_path, "rpc", {"mode": "ok", "channel": "subagents:rpc:schedule_remove", "jobId": "j9"})["reply"]
    assert ok == {"success": True, "data": {"echo": "j9"}}
    timeout = drive(tmp_path, "rpc", {"mode": "timeout", "channel": "subagents:rpc:schedule_remove", "timeoutMs": 80})["reply"]
    assert timeout["success"] is False and "timeout" in timeout["error"]


def test_validate_patch_whitelist_and_formats(tmp_path) -> None:
    assert drive(tmp_path, "validate", {"patch": {"schedule": "0 5 8 * * *"}})["error"] is None
    assert drive(tmp_path, "validate", {"patch": {"schedule": "2026-11-07T00:00:00.000Z"}})["error"] is None
    assert drive(tmp_path, "validate", {"patch": {"enabled": False, "prompt": "x"}})["error"] is None
    assert "不允许改 id" in drive(tmp_path, "validate", {"patch": {"id": "evil"}})["error"]
    assert "6 字段 cron" in drive(tmp_path, "validate", {"patch": {"schedule": "0 5 8 * *"}})["error"]
    assert "ISO" in drive(tmp_path, "validate", {"patch": {"schedule": "not-a-date"}})["error"]


def test_store_path_layout(tmp_path) -> None:
    assert drive(tmp_path, "path", {"cwd": "/w", "sessionId": "s"})["path"] == "/w/.pi/subagent-schedules/s.json"


def test_list_jobs_sources(tmp_path) -> None:
    store = tmp_path / ".pi" / "subagent-schedules"
    store.mkdir(parents=True)
    (store / "sess-1.json").write_text(json.dumps({"version": 1, "jobs": [JOB]}), encoding="utf8")
    assert drive(tmp_path, "jobs", {"upstream": "list", "job": JOB})["outcome"] == {"status": "ok", "source": "rpc", "jobs": [JOB]}
    assert drive(tmp_path, "jobs", {"upstream": "throw"})["outcome"]["source"] == "file"
    assert drive(tmp_path, "jobs", {})["outcome"] == {"status": "ok", "source": "file", "jobs": [JOB]}
    assert drive(tmp_path, "jobs", {"noSessionId": True, "upstream": "list"})["outcome"] == {"status": "no-session"}
    assert drive(tmp_path, "jobs", {"sessionId": "sess-2"})["outcome"] == {"status": "no-store"}


def test_workflow_journal_tail_fallback(tmp_path) -> None:
    entries = [{"index": 0, "ok": True, "text": "a"}, {"index": 1, "ok": False}, {"index": 2, "ok": True, "text": "c"}]
    out = drive(tmp_path, "journal-tail", {"makeFiles": entries, "lines": 2})
    assert out["tail"] == {"total": 3, "okCount": 2, "indexes": [1, 2]}
    assert out["badId"] is None and out["dirOverride"] == str(tmp_path) and out["encode"] == "home-remedy-workspace-x y"
    assert drive(tmp_path, "journal-tail", {"fresh": True})["tail"] is None
    alone = drive(tmp_path, "journal-tail", {"makeFiles": [{"index": 0, "ok": False}]})
    assert alone["tail"]["okCount"] == 0


def test_bg_list_all_sections_with_handles(tmp_path) -> None:
    created = tools({"upstream": {"list": {"agents": [AGENT_RUNNING]}, "workflow_list": {"runs": []}}, "calls": [{"tool": "task_create", "params": {"cmd": "sleep 2", "name": "巡查"}}]}, tmp_path)[0]
    task_id = created["details"]["id"]
    listing, stopped = tools({"upstream": {"list": {"agents": [AGENT_RUNNING, AGENT_ERROR]}, "workflow_list": {"runs": [RUN]}, "schedule_list": [JOB]}, "calls": [
        {"tool": "bg_list", "params": {}},
        {"tool": "bg_stop", "params": {"handle": f"task:{task_id}"}},
    ]}, tmp_path)
    assert listing["isError"] is False
    for fragment in ("[task] 命令任务 1 个在跑", f"task:{task_id} | running", "[agent] 子代理 2 个", "agent:agent-run1 @watcher | running", "agent:agent-err1 | error", "[wf] workflow run 1 个", "wf:wf_abc123def456 | hub-log-watch | running | agents 2/5", "[job] 定时任务 1 个:", "job:W6E5_nfAyQ"):
        assert fragment in listing["text"], fragment
    assert listing["details"]["wf"]["source"] == "rpc" and listing["details"]["job"]["source"] == "rpc" and listing["details"]["task"]["tasks"] == [task_id]
    assert "已停止" in stopped["text"]


def test_bg_list_degrades_per_section(tmp_path) -> None:
    out = drive(tmp_path, "tools", {"features": NO_LIST, "calls": [{"tool": "bg_list", "params": {}}]})
    names = out["names"]
    agent_note = out["results"][0]["text"]
    assert "[agent] " in agent_note and "快照通道" in agent_note and "unavailable" not in agent_note
    absent = drive(tmp_path, "tools", {"features": None, "calls": [{"tool": "bg_list", "params": {}}, {"tool": "bg_list", "params": {"kind": "agent"}}]})["results"]
    assert absent[0]["text"] == "无后台事务" and absent[1]["text"] == "无子代理(本会话没有 pi-subagents)"
    store = tmp_path / ".pi" / "subagent-schedules"
    store.mkdir(parents=True)
    (store / "sess-1.json").write_text(json.dumps({"version": 1, "jobs": [JOB]}), encoding="utf8")
    mirrored, bad = tools({"features": NO_KIT, "calls": [{"tool": "bg_list", "params": {"kind": "job"}}, {"tool": "bg_list", "params": {"kind": "nope"}}]}, tmp_path)
    assert "只读镜像" in mirrored["text"] and "job:W6E5_nfAyQ" in mirrored["text"] and mirrored["isError"] is False
    assert bad["isError"] is True and "kind 需为" in bad["text"]
    assert names == ["bg_list", "bg_log", "bg_schedule", "bg_status", "bg_stop", "task_create"]


def test_bg_status_waits_for_agent_terminal(tmp_path) -> None:
    flip = {"flipAfterMs": 800, "data": {"agents": [AGENT_RUNNING]}, "then": {"agents": [AGENT_DONE]}}
    waited, named, ghost = tools({"upstream": {"list": flip}, "calls": [
        {"tool": "bg_status", "params": {"handle": "agent:agent-run1", "wait": 6}},
        {"tool": "bg_status", "params": {"handle": "agent:@watcher"}},
        {"tool": "bg_status", "params": {"handle": "agent:@ghost"}},
    ]}, tmp_path)
    assert waited["details"]["status"] == "completed" and 700 <= waited["details"]["waitedMs"] < 6000
    assert "agent:agent-run1 @watcher | completed" in waited["text"] and "result(尾 300 字):" in waited["text"] and "waited=" in waited["text"]
    assert "completed" in named["text"]
    assert ghost["isError"] is True and "无子代理 @ghost" in ghost["text"]
    failed = tools({"upstream": {"list": {"agents": [AGENT_ERROR]}}, "calls": [{"tool": "bg_status", "params": {"handle": "agent:agent-err1"}}]}, tmp_path)[0]
    assert "error: model timeout after 3 retries" in failed["text"] and "result(" not in failed["text"]


def test_bg_status_failed_agent_with_empty_result_prints_no_result_line(tmp_path) -> None:
    failed_with_empty_result = {**AGENT_ERROR, "result": ""}
    failed = tools({"upstream": {"list": {"agents": [failed_with_empty_result]}}, "calls": [{"tool": "bg_status", "params": {"handle": "agent:agent-err1"}}]}, tmp_path)[0]
    assert "error: model timeout after 3 retries" in failed["text"] and "result(" not in failed["text"]
    assert failed["details"]["status"] == "error"


def test_bg_status_agent_shows_session_label(tmp_path) -> None:
    label = "v8-audit · agent · 父:01a221a5 · general-purpose#984b6192"
    calls = [{"tool": "bg_status", "params": {"handle": "agent:agent-run1"}}]
    shown = tools({"upstream": {"list": {"agents": [{**AGENT_DONE, "sessionName": label}]}}, "calls": calls}, tmp_path)[0]
    plain = tools({"upstream": {"list": {"agents": [AGENT_DONE]}}, "calls": calls}, tmp_path)[0]
    assert f"标签: {label}" in shown["text"] and shown["text"].index("标签:") < shown["text"].index("result(尾")
    assert "标签:" not in plain["text"]


def test_bg_status_workflow_rpc_and_journal_fallback(tmp_path) -> None:
    detail = tools({"upstream": {"workflow_status": STATUS_DETAIL, "workflow_list": {"runs": []}}, "calls": [{"tool": "bg_status", "params": {"handle": "wf:wf_abc123def456"}}]}, tmp_path)[0]
    assert "[error] | rpc timeout" in detail["text"] and detail["details"]["waitedMs"] == 0
    ghost = tools({"upstream": {"workflow_status": {"throw": "no such workflow run: wf_nope"}}, "calls": [{"tool": "bg_status", "params": {"handle": "wf:wf_nope"}}]}, tmp_path)[0]
    assert ghost["isError"] is True and "无 workflow run wf_nope" in ghost["text"]
    journaled = tools({"features": NO_KIT, "journal": [{"index": 0, "ok": True, "text": "a"}, {"index": 1, "ok": False, "text": "b"}], "calls": [{"tool": "bg_status", "params": {"handle": "wf:wf_test1234"}}]}, tmp_path)[0]
    assert "[journal 降级]" in journaled["text"] and "#1 FAILED b" in journaled["text"] and journaled["details"]["source"] == "journal"
    missing = tools({"features": None, "calls": [{"tool": "bg_status", "params": {"handle": "wf:wf_test1234"}}]}, tmp_path)[0]
    assert missing["isError"] is True and "没有 pi-subagents" in missing["text"]


def test_bg_status_idle_waits_for_everything(tmp_path) -> None:
    results = tools({"upstream": {"list": {"flipAfterMs": 800, "data": {"agents": [AGENT_RUNNING]}, "then": {"agents": [AGENT_DONE]}}, "workflow_list": {"runs": [dict(RUN, status="completed")]}}, "calls": [
        {"tool": "task_create", "params": {"cmd": "sleep 1; exit 0"}},
        {"tool": "bg_status", "params": {"until": "idle"}},
        {"tool": "bg_status", "params": {"until": "idle", "wait": 8}},
        {"tool": "bg_status", "params": {"until": "bogus"}},
        {"tool": "bg_status", "params": {}},
    ]}, tmp_path)
    task_id = results[0]["details"]["id"]
    busy, idle, bogus, bare = results[1:]
    assert busy["details"]["idle"] is False and f"task:{task_id}" in busy["text"] and "agent:agent-run1" in busy["text"] and "wf:" not in busy["text"]
    assert idle["details"]["idle"] is True and 700 <= idle["details"]["waitedMs"] < 8000 and "已空闲" in idle["text"]
    assert bogus["isError"] is True and "until 需为" in bogus["text"]
    assert bare["isError"] is True and "缺句柄" in bare["text"]
    noted = tools({"features": NO_KIT, "calls": [{"tool": "bg_status", "params": {"until": "idle"}}]}, tmp_path)[0]
    assert noted["details"]["idle"] is True and "workflow 运行态不可得" in noted["text"]


def test_bg_log_agent_transcript(tmp_path) -> None:
    entries = [{"type": "message", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "sleep 1"}}]}}, {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "第一步"}]}}] * 8
    tail = tools({"agents": [dict(AGENT_RUNNING, sessionFile="$transcript")], "transcript": entries, "calls": [{"tool": "bg_log", "params": {"handle": "agent:agent-run1"}}]}, tmp_path)[0]
    ghost = tools({"upstream": {"list": {"agents": [dict(AGENT_RUNNING)]}}, "calls": [{"tool": "bg_log", "params": {"handle": "agent:@ghost"}}]}, tmp_path)[0]
    assert len(tail["text"].split("\n")) == 13 and tail["text"].split("\n")[-1] == f"[cursor={tail['details']['cursor']} state=running]"
    assert ghost["isError"] is True
    cursor = tail["details"]["cursor"]
    drained = tools({"agents": [dict(AGENT_RUNNING, sessionFile="$transcript")], "transcript": entries, "calls": [{"tool": "bg_log", "params": {"handle": "agent:agent-run1", "since": cursor}}]}, tmp_path)[0]
    assert drained["text"].startswith("(无可读记录)")
    grown = tools({"agents": [dict(AGENT_RUNNING, sessionFile="$transcript")], "transcript": entries + [{"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "新增一步"}]}}], "calls": [{"tool": "bg_log", "params": {"handle": "agent:agent-run1", "since": cursor}}]}, tmp_path)[0]
    assert grown["details"]["rows"] == ["新增一步"]
    detached = tools({"upstream": {"list": {"agents": [dict(AGENT_DONE)]}}, "calls": [{"tool": "bg_log", "params": {"handle": "agent:agent-run1"}}]}, tmp_path)[0]
    assert "没有可读的会话记录" in detached["text"] and detached["isError"] is False


def test_bg_log_workflow_lines_incremental(tmp_path) -> None:
    numbered, drained, job = tools({"upstream": {"workflow_status": STATUS_DETAIL}, "calls": [
        {"tool": "bg_log", "params": {"handle": "wf:wf_abc123def456"}},
        {"tool": "bg_log", "params": {"handle": "wf:wf_abc123def456", "since": 3}},
        {"tool": "bg_log", "params": {"handle": "job:W6E5"}},
    ]}, tmp_path)
    assert "1 守窗第 1 轮\n2 安静,推进偏移" in numbered["text"] and "[cursor=3 state=running]" in numbered["text"]
    assert "没有更新的 log()" in drained["text"] and "[cursor=3" in drained["text"]
    assert job["isError"] is True and "bg_schedule" in job["text"]
    journaled = tools({"features": NO_KIT, "journal": [{"index": 0, "ok": True, "text": "a"}, {"index": 1, "ok": True, "text": "b"}], "calls": [{"tool": "bg_log", "params": {"handle": "wf:wf_test1234", "since": 1}}]}, tmp_path)[0]
    assert "log() 叙述(journal 降级,RPC 不可达):\n1 ok b" in journaled["text"] and journaled["text"].endswith("[cursor=2 state=journal]")


def test_bg_stop_paths(tmp_path) -> None:
    created = tools({"upstream": {}, "calls": [{"tool": "task_create", "params": {"cmd": "sleep 30", "name": "长跑"}}]}, tmp_path)[0]
    stopped, again, bad = tools({"upstream": {}, "calls": [{"tool": "bg_stop", "params": {"handle": f"task:{created['details']['id']}"}}, {"tool": "bg_stop", "params": {"handle": f"task:{created['details']['id']}"}}, {"tool": "bg_stop", "params": {"handle": "task:ghost"}}]}, tmp_path)
    assert "已停止" in stopped["text"] and stopped["details"]["state"] == "exited" and again["isError"] is False and "幂等跳过" in again["text"]
    assert bad["isError"] is True and "无后台命令任务 ghost" in bad["text"]
    ok = tools({"upstream": {"stop": {}, "list": {"agents": [AGENT_RUNNING]}}, "calls": [{"tool": "bg_stop", "params": {"handle": "agent:agent-run1"}}]}, tmp_path)[0]
    named = tools({"upstream": {"stop": {}, "list": {"agents": [AGENT_RUNNING]}}, "calls": [{"tool": "bg_stop", "params": {"handle": "agent:@watcher"}}]}, tmp_path)[0]
    settled = tools({"upstream": {"stop": {"throw": "Agent is not running"}, "list": {"agents": [AGENT_RUNNING]}}, "calls": [{"tool": "bg_stop", "params": {"handle": "agent:agent-run1"}}]}, tmp_path)[0]
    owned = tools({"upstream": {"stop": {"throw": "Agent is owned by another agent or workflow"}, "list": {"agents": [AGENT_RUNNING]}}, "calls": [{"tool": "bg_stop", "params": {"handle": "agent:agent-run1"}}]}, tmp_path)[0]
    assert ok["text"] == "已停止 agent:agent-run1" and named["text"] == "已停止 agent:agent-run1"
    assert settled["isError"] is False and "幂等跳过" in settled["text"]
    assert owned["isError"] is True and "停整个 run" in owned["text"]
    run = tools({"upstream": {"workflow_stop": {"stopped": True}}, "calls": [{"tool": "bg_stop", "params": {"handle": "wf:wf_abc123def456"}}]}, tmp_path)[0]
    run_again = tools({"upstream": {"workflow_stop": {"stopped": False, "status": "killed"}}, "calls": [{"tool": "bg_stop", "params": {"handle": "wf:wf_abc123def456"}}]}, tmp_path)[0]
    assert "已停止 wf:wf_abc123def456(" in run["text"] and "续跑用 SubagentWorkflow" in run["text"] and "wf:wf_abc123def456 无需停止" in run_again["text"] and "killed" in run_again["text"]
    job, broken = tools({"calls": [{"tool": "bg_stop", "params": {"handle": "job:W6E5"}}, {"tool": "bg_stop", "params": {"handle": "sleep 1"}}]}, tmp_path)
    assert job["isError"] is True and "enabled=false" in job["text"] and broken["isError"] is True and "句柄格式不对" in broken["text"]


def test_bg_schedule_paths(tmp_path) -> None:
    listed = tools({"upstream": {"schedule_list": [JOB]}, "calls": [{"tool": "bg_schedule", "params": {"action": "list"}}]}, tmp_path)[0]
    assert "job:W6E5_nfAyQ" in listed["text"] and "只读镜像" not in listed["text"]
    empty, bad_action, no_handle = tools({"features": NO_KIT, "calls": [{"tool": "bg_schedule", "params": {"action": "list"}}, {"tool": "bg_schedule", "params": {"action": "purge"}}, {"tool": "bg_schedule", "params": {"action": "cancel"}}]}, tmp_path)
    assert empty["text"] == "无定时任务" and empty["isError"] is False and "只读镜像" not in empty["text"]
    assert bad_action["isError"] is True and "action 需为" in bad_action["text"]
    assert no_handle["isError"] is True and "job:<id>" in no_handle["text"]
    cancelled, update, invalid = tools({"upstream": {"schedule_remove": {}, "schedule_update": dict(JOB, schedule="0 5 8 * * *", scheduleType="cron", enabled=False, nextRun="2026-11-29T00:05:00.000Z")}, "calls": [
        {"tool": "bg_schedule", "params": {"action": "cancel", "handle": "job:W6E5_nfAyQ"}},
        {"tool": "bg_schedule", "params": {"action": "update", "handle": "job:W6E5_nfAyQ", "schedule": "0 5 8 * * *", "enabled": False}},
        {"tool": "bg_schedule", "params": {"action": "update", "handle": "job:W6E5_nfAyQ", "schedule": "0 5 8"}},
    ]}, tmp_path)
    assert "已取消 job:W6E5_nfAyQ" in cancelled["text"]
    assert update["text"] == "已更新 job:W6E5_nfAyQ → cron 0 5 8 * * * (disabled) 下次 2026-11-29T00:05:00.000Z"
    assert invalid["isError"] is True and "6 字段 cron" in invalid["text"]
    gone = tools({"upstream": {"schedule_remove": {"throw": "no such job: W6E5_nfAyQ"}}, "calls": [{"tool": "bg_schedule", "params": {"action": "cancel", "handle": "job:W6E5_nfAyQ"}}]}, tmp_path)[0]
    unpatched = tools({"features": NO_KIT, "calls": [{"tool": "bg_schedule", "params": {"action": "cancel", "handle": "job:W6E5_nfAyQ"}}]}, tmp_path)[0]
    absent = tools({"features": None, "calls": [{"tool": "bg_schedule", "params": {"action": "cancel", "handle": "job:W6E5_nfAyQ"}}]}, tmp_path)[0]
    assert "no such job" in gone["text"] and gone["isError"] is True
    assert "缺定时任务写通道" in unpatched["text"] and "没有 pi-subagents" in absent["text"]
