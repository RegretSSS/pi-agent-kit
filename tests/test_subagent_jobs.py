import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "subagent_jobs_driver.mjs"
PATCH = REPO / "scripts" / "patch-subagents-schedule-rpc.mjs"

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


def drive(scenario: str, payload: dict) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), scenario, json.dumps(payload, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_format_rows_and_source_tail() -> None:
    assert drive("format", {"jobs": []})["text"] == "无定时任务"
    text = drive("format", {"jobs": [JOB]})["text"]
    assert "- W6E5_nfAyQ | 每日晨报巡查agent | once 2026-11-06T00:00:00.000Z | enabled | 已跑 0 次 | 下次 2026-11-06T00:00:00.000Z" in text
    assert "/agents" in text
    rpc_tail = drive("format", {"jobs": [JOB], "source": "rpc"})["text"]
    assert "job_cancel / job_reschedule" in rpc_tail
    assert "patch 未打" not in rpc_tail


def test_list_prefers_rpc_over_file(tmp_path) -> None:
    out = drive("rpc", {"cwd": str(tmp_path), "upstream": "list"})
    outcome = out["outcome"]
    assert outcome["status"] == "ok"
    assert outcome["source"] == "rpc"
    assert outcome["jobs"][0]["nextRun"] == "2026-11-06T00:00:00.000Z"


def test_list_falls_back_to_file_when_upstream_throws(tmp_path) -> None:
    store = tmp_path / ".pi" / "subagent-schedules"
    store.mkdir(parents=True)
    (store / "sess-1.json").write_text(json.dumps({"version": 1, "jobs": [JOB]}), encoding="utf8")
    outcome = drive("rpc", {"cwd": str(tmp_path), "sessionId": "sess-1", "upstream": "throw"})["outcome"]
    assert outcome["status"] == "ok"
    assert outcome["source"] == "file"


def test_list_file_fallback_when_no_upstream(tmp_path) -> None:
    assert drive("rpc", {"cwd": str(tmp_path)})["outcome"]["status"] == "no-store"


def test_list_without_session_id(tmp_path) -> None:
    assert drive("rpc", {"cwd": str(tmp_path), "noSessionId": True, "upstream": "list"})["outcome"]["status"] == "no-session"


def test_rpc_call_ok_and_timeout() -> None:
    ok = drive("call", {"mode": "ok", "channel": "subagents:rpc:schedule_remove", "jobId": "j9"})["reply"]
    assert ok == {"success": True, "data": {"echo": "j9"}}
    timeout = drive("call", {"mode": "timeout", "channel": "subagents:rpc:schedule_remove", "timeoutMs": 80})["reply"]
    assert timeout["success"] is False
    assert "timeout" in timeout["error"]


def test_validate_patch_whitelist_and_formats() -> None:
    assert drive("validate", {"patch": {"schedule": "0 5 8 * * *"}})["error"] is None
    assert drive("validate", {"patch": {"schedule": "2026-11-07T00:00:00.000Z"}})["error"] is None
    assert drive("validate", {"patch": {"enabled": False, "prompt": "x"}})["error"] is None
    assert "不允许改 id" in drive("validate", {"patch": {"id": "evil"}})["error"]
    assert "6 字段 cron" in drive("validate", {"patch": {"schedule": "0 5 8 * *"}})["error"]
    assert "ISO" in drive("validate", {"patch": {"schedule": "not-a-date"}})["error"]


def test_store_path_layout() -> None:
    assert drive("path", {"cwd": "/w", "sessionId": "s"})["path"] == "/w/.pi/subagent-schedules/s.json"


def make_fake_upstream(home: Path) -> None:
    src_dir = home / ".pi/agent/npm/node_modules/@tintinweb/pi-subagents/src"
    src_dir.mkdir(parents=True)
    (src_dir / "cross-extension-rpc.ts").write_text(
        'import type { AgentRecord } from "./types.js";\n'
        "export interface RpcDeps {\n"
        "  events: EventBus;\n"
        "  pi: unknown;\n"
        "  getCtx: () => unknown | undefined;\n"
        "  manager: SpawnCapable;\n"
        "}\n"
        '  const unsubPing = handleRpc(events, "subagents:rpc:ping", () => {\n'
        "    return { version: PROTOCOL_VERSION };\n"
        "  });\n"
        "  const unsubSpawn = handleRpc<{ requestId: string; type: string; prompt: string; options?: any }>(\n",
        encoding="utf8",
    )
    desc_dir = src_dir / "workflow"
    desc_dir.mkdir(parents=True)
    (desc_dir / "tool-description.ts").write_text(
        "export const fullWorkflowToolDescription = `placeholder`;\n"
        "stamp results after the workflow returns, or pass timestamps via args.`;\n",
        encoding="utf8",
    )
    (src_dir / "index.ts").write_text(
        'import { fullWorkflowToolDescription } from "./workflow/tool-description.js";\n'
        "      rpcHandle = registerRpcHandlers({\n"
        "        events: pi.events,\n"
        "        pi,\n"
        "        getCtx: () => currentCtx,\n"
        "description: renderToolDescriptionTemplate(fullWorkflowToolDescription),\n",
        encoding="utf8",
    )


def run_patch(home: Path, tmp: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(home))
    if tmp is not None:
        env["TMPDIR"] = str(tmp)
    return subprocess.run(["node", str(PATCH)], capture_output=True, text=True, env=env, cwd=REPO)


def test_patch_script_idempotent_and_anchored(tmp_path) -> None:
    home = tmp_path
    tmp = tmp_path / "tmpdir"
    jiti = tmp / "jiti" / "nested"
    jiti.mkdir(parents=True)
    (jiti / "stale.mjs").write_text("old cache", encoding="utf8")
    make_fake_upstream(home)
    first = run_patch(home, tmp)
    assert first.returncode == 0, first.stderr
    assert first.stdout.count("注入完成") == 10
    rpc_text = (home / ".pi/agent/npm/node_modules/@tintinweb/pi-subagents/src/cross-extension-rpc.ts").read_text()
    assert "subagents:rpc:schedule_list" in rpc_text
    assert "requireScheduler" in rpc_text
    assert "getScheduler?: () => unknown;" in rpc_text
    assert "getWorkflowTasks?: () => unknown;" in rpc_text
    assert "subagents:rpc:workflow_list" in rpc_text
    assert "subagents:rpc:workflow_stop" in rpc_text
    assert "subagents:rpc:workflow_pause" in rpc_text
    assert "subagents:rpc:workflow_resume" in rpc_text
    assert "subagents:rpc:workflow_status" in rpc_text
    assert "pauseWorkflowTask" in rpc_text
    assert 'from "./workflow/progress.js"' in rpc_text
    assert 'from "./workflow/task.js"' in rpc_text
    index_text = (home / ".pi/agent/npm/node_modules/@tintinweb/pi-subagents/src/index.ts").read_text()
    assert "getScheduler: () => scheduler," in index_text
    assert "getWorkflowTasks: () => workflowTasks," in index_text
    rpc_text2 = (home / ".pi/agent/npm/node_modules/@tintinweb/pi-subagents/src/workflow/tool-description.ts").read_text()
    assert "slimWorkflowToolDescription" in rpc_text2
    assert "read the skill 'subagent-workflows'" in rpc_text2
    assert "renderToolDescriptionTemplate(slimWorkflowToolDescription)," in index_text
    assert "import { fullWorkflowToolDescription, slimWorkflowToolDescription }" in index_text
    assert not (tmp / "jiti").exists()
    second = run_patch(home, tmp)
    assert second.returncode == 0
    assert second.stdout.count("已打过") == 10
    assert "已清理 jiti" in second.stdout


def test_patch_script_fails_cleanly_on_anchor_miss(tmp_path) -> None:
    home = tmp_path
    src_dir = home / ".pi/agent/npm/node_modules/@tintinweb/pi-subagents/src"
    src_dir.mkdir(parents=True)
    (src_dir / "cross-extension-rpc.ts").write_text("upgraded beyond recognition", encoding="utf8")
    desc_dir = src_dir / "workflow"
    desc_dir.mkdir(parents=True)
    (desc_dir / "tool-description.ts").write_text(
        "export const fullWorkflowToolDescription = `placeholder`;\n"
        "stamp results after the workflow returns, or pass timestamps via args.`;\n",
        encoding="utf8",
    )
    (src_dir / "index.ts").write_text("anything", encoding="utf8")
    result = run_patch(home, tmp_path)
    assert result.returncode == 1
    assert "锚点未命中" in result.stdout + result.stderr


def test_workflow_run_formatting() -> None:
    empty = drive("wf-format", {"runs": []})["runsText"]
    assert empty.startswith("本会话还没有 workflow run")
    text = drive("wf-format", {"runs": [RUN]})["runsText"]
    assert "- wf_abc123def456 | hub-log-watch | running | agents 2/5 | tokens 1234" in text
    assert "workflow_stop / workflow_pause / workflow_resume" in text
    assert "resumeFromRunId" in text
    status = drive("wf-format", {"runs": [], "detail": STATUS_DETAIL})["statusText"]
    assert status.split("\n")[0].startswith("- wf_abc123def456")
    assert "script: /s/template.js" in status
    assert "journal: /s/journal.jsonl" in status
    assert "[done] tokens 800" in status
    assert "[error] | rpc timeout" in status
    assert "安静,推进偏移" in status


def test_workflow_tools_behavior() -> None:
    out = drive("wf-tools", {
        "tool": "workflow_list",
        "upstream": {"subagents:rpc:workflow_list": {"data": {"runs": [RUN]}}},
    })["result"]
    assert out["isError"] is False
    assert "wf_abc123def456" in out["text"]

    out = drive("wf-tools", {
        "tool": "workflow_list",
        "upstream": {"subagents:rpc:workflow_list": {"throw": "workflow registry unavailable"}},
    })["result"]
    assert out["isError"] is True
    assert "workflow-rpc patch" in out["text"]

    out = drive("wf-tools", {
        "tool": "workflow_stop",
        "params": {"run_id": "wf_abc123def456"},
        "upstream": {"subagents:rpc:workflow_stop": {"data": {"stopped": True}}},
    })["result"]
    assert out["isError"] is False
    assert "已停止 wf_abc123def456" in out["text"]
    assert "resumeFromRunId" in out["text"]

    out = drive("wf-tools", {
        "tool": "workflow_stop",
        "params": {"run_id": "wf_abc123def456"},
        "upstream": {"subagents:rpc:workflow_stop": {"data": {"stopped": False, "status": "killed"}}},
    })["result"]
    assert out["isError"] is False
    assert "无需停止" in out["text"]
    assert "killed" in out["text"]

    out = drive("wf-tools", {
        "tool": "workflow_status",
        "params": {"run_id": "wf_abc123def456", "lines": 5},
        "upstream": {"subagents:rpc:workflow_status": {"data": STATUS_DETAIL}},
    })["result"]
    assert out["isError"] is False
    assert "[error] | rpc timeout" in out["text"]

    out = drive("wf-tools", {
        "tool": "workflow_pause",
        "params": {"run_id": "wf_abc123def456"},
        "upstream": {"subagents:rpc:workflow_pause": {"throw": "run wf_abc123def456 cannot pause now (status: completed)"}},
    })["result"]
    assert out["isError"] is True
    assert "cannot pause now" in out["text"]
