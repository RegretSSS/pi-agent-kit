import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "compact_tool_driver.mjs"


def drive(scenario: str, payload: dict | None = None) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), scenario, json.dumps(payload or {}, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_wakeup_uses_steer_delivery() -> None:
    out = drive("wakeup", {"reason": "threshold", "willRetry": False, "sessionFile": "/x.jsonl"})
    assert out["sentOptions"][0] == {"deliverAs": "steer"}


def test_wakeup_injected_after_compact() -> None:
    out = drive("wakeup", {"reason": "threshold", "willRetry": False, "sessionFile": "/home/x/sessions/2026-11-11.jsonl"})
    assert "/home/x/sessions/2026-11-11.jsonl" in out["sent"][0]
    assert "read/grep" in out["sent"][0]
    assert len(out["sent"]) == 1
    assert out["sent"][0].startswith("[compact 完成]")
    assert "fold-index" in out["sent"][0]
    assert "水位触发" in out["sent"][0]


def test_wakeup_manual_reason_labeled() -> None:
    out = drive("wakeup", {"reason": "manual", "willRetry": False})
    assert "手动 /compact" in out["sent"][0]


def test_wakeup_without_session_file_still_sent() -> None:
    out = drive("wakeup", {"reason": "threshold", "willRetry": False, "sessionFile": None})
    assert out["sent"][0].startswith("[compact 完成]")
    assert "本会话文件" not in out["sent"][0]


def test_wakeup_suppressed_on_retry() -> None:
    out = drive("wakeup", {"willRetry": True})
    assert out["sent"] == []


def test_instructions_carry_gauge_contract() -> None:
    out = drive("instructions", {"brief": "keep task state"})
    assert "keep task state" in out["text"]
    assert "<fold-index>" in out["text"]
    source = (REPO / "extensions" / "compact-tool.ts").read_text(encoding="utf-8")
    assert "30%" in source and "50%" in source
