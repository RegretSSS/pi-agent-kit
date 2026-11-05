import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "context_gauge_driver.mjs"


def drive(scenario: str, payload: dict) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), scenario, json.dumps(payload, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_gauge_line_tiers() -> None:
    assert drive("line", {"tokens": 124000, "contextWindow": 200000})["line"] == "[ctx 62% 124k/200k]"
    warn = drive("line", {"tokens": 152000, "contextWindow": 200000})["line"]
    assert warn.startswith("[ctx 76% 152k/200k")
    assert "75%建议线" in warn
    urgent = drive("line", {"tokens": 182000, "contextWindow": 200000})["line"]
    assert urgent.startswith("[ctx 91% 182k/200k")
    assert "90%紧迫线" in urgent


def test_first_tool_result_of_turn_gets_gauge() -> None:
    out = drive("attach", {"steps": [{"usage": {"tokens": 124000, "window": 200000, "percent": 62}}, {"usage": {"tokens": 130000, "window": 200000, "percent": 65}}]})
    assert out["results"][0]["appended"] == "[ctx 62% 124k/200k]"
    assert out["results"][0]["original"] == "tool output"
    assert out["results"][1]["appended"] is None


def test_error_result_skipped_until_healthy() -> None:
    out = drive("attach", {"steps": [{"isError": True, "usage": {"tokens": 124000, "window": 200000, "percent": 62}}, {"usage": {"tokens": 124000, "window": 200000, "percent": 62}}]})
    assert out["results"][0]["appended"] is None
    assert out["results"][1]["appended"] == "[ctx 62% 124k/200k]"


def test_turn_start_resets_attachment() -> None:
    out = drive("attach", {"steps": [
        {"usage": {"tokens": 124000, "window": 200000, "percent": 62}},
        {"turnStart": True},
        {"usage": {"tokens": 130000, "window": 200000, "percent": 65}},
    ]})
    assert out["results"][0]["appended"] is not None
    assert out["results"][1]["appended"] == "[ctx 65% 130k/200k]"


def test_unknown_usage_no_attach() -> None:
    out = drive("attach", {"steps": [{"usage": None}, {"usage": {"tokens": 124000, "window": 200000, "percent": 62}}]})
    assert out["results"][0]["appended"] is None
    assert out["results"][1]["appended"] == "[ctx 62% 124k/200k]"


def test_structured_content_preserved() -> None:
    out = drive("attach", {"steps": [
        {"usage": {"tokens": 124000, "window": 200000, "percent": 62}, "structuredContent": {"rows": 3}},
        {"turnStart": True},
        {"usage": {"tokens": 124000, "window": 200000, "percent": 62}},
    ]})
    assert out["results"][0]["structuredContent"] == {"rows": 3}
    assert out["results"][1]["structuredContent"] is None


def test_footer_status_only_with_ui() -> None:
    with_ui = drive("attach", {"steps": [{"hasUI": True, "usage": {"tokens": 124000, "window": 200000, "percent": 62}}]})
    assert with_ui["statuses"] == ["ctx 62% 124k/200k"]
    without_ui = drive("attach", {"steps": [{"hasUI": False, "usage": {"tokens": 124000, "window": 200000, "percent": 62}}]})
    assert without_ui["statuses"] == []
