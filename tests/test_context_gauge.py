import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "context_gauge_driver.mjs"
CLOCK_RE = r" \| \d{4}-\d{2}-\d{2} \d{2}:\d{2} 周[一二三四五六日]\(UTC[+-]\d+(?:\.\d)?\)\]$"


def drive(scenario: str, payload: dict) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), scenario, json.dumps(payload, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_gauge_line_tiers_with_clock() -> None:
    normal = drive("line", {"tokens": 124000, "contextWindow": 200000})["line"]
    assert re.fullmatch(r"\[ctx 62% 124k/200k" + CLOCK_RE, normal)
    warn = drive("line", {"tokens": 152000, "contextWindow": 200000})["line"]
    assert warn.startswith("[ctx 76% 152k/200k")
    assert "75%建议线" in warn
    assert re.search(CLOCK_RE, warn)
    urgent = drive("line", {"tokens": 182000, "contextWindow": 200000})["line"]
    assert urgent.startswith("[ctx 91% 182k/200k")
    assert "90%紧迫线" in urgent
    assert re.search(CLOCK_RE, urgent)


def test_first_result_reports_then_throttled() -> None:
    out = drive("attach", {"steps": [
        {"usage": {"tokens": 124000, "window": 200000, "percent": 62}},
        {"usage": {"tokens": 126000, "window": 200000, "percent": 63}},
    ]})
    assert re.fullmatch(r"\[ctx 62% 124k/200k" + CLOCK_RE, out["results"][0]["appended"])
    assert out["results"][1]["appended"] is None


def test_tier_cross_bypasses_throttle() -> None:
    out = drive("attach", {"steps": [
        {"usage": {"tokens": 124000, "window": 200000, "percent": 62}},
        {"usage": {"tokens": 156000, "window": 200000, "percent": 78}},
    ]})
    assert out["results"][0]["appended"] is not None
    assert out["results"][1]["appended"] is not None
    assert "75%建议线" in out["results"][1]["appended"]


def test_compact_resets_throttle() -> None:
    out = drive("attach", {"steps": [
        {"usage": {"tokens": 124000, "window": 200000, "percent": 62}},
        {"compact": True},
        {"usage": {"tokens": 60000, "window": 200000, "percent": 30}},
    ]})
    assert out["results"][0]["appended"] is not None
    assert re.fullmatch(r"\[ctx 30% 60k/200k" + CLOCK_RE, out["results"][1]["appended"])


def test_error_result_also_reported() -> None:
    out = drive("attach", {"steps": [{"isError": True, "usage": {"tokens": 124000, "window": 200000, "percent": 62}}]})
    assert re.fullmatch(r"\[ctx 62% 124k/200k" + CLOCK_RE, out["results"][0]["appended"])


def test_unknown_usage_no_attach() -> None:
    out = drive("attach", {"steps": [{"usage": None}, {"usage": {"tokens": 124000, "window": 200000, "percent": 62}}]})
    assert out["results"][0]["appended"] is None
    assert re.fullmatch(r"\[ctx 62% 124k/200k" + CLOCK_RE, out["results"][1]["appended"])


def test_structured_content_preserved() -> None:
    out = drive("attach", {"steps": [
        {"usage": {"tokens": 124000, "window": 200000, "percent": 62}, "structuredContent": {"rows": 3}},
        {"usage": {"tokens": 124000, "window": 200000, "percent": 62}},
    ]})
    assert out["results"][0]["structuredContent"] == {"rows": 3}
    assert out["results"][1]["structuredContent"] is None


def test_footer_status_only_with_ui() -> None:
    with_ui = drive("attach", {"steps": [{"hasUI": True, "usage": {"tokens": 124000, "window": 200000, "percent": 62}}, {"hasUI": True, "usage": {"tokens": 126000, "window": 200000, "percent": 63}}]})
    assert len(with_ui["statuses"]) == 2
    assert re.fullmatch(r"ctx 62% 124k/200k \| \d{4}-\d{2}-\d{2} \d{2}:\d{2} 周[一二三四五六日]\(UTC[+-]\d+(?:\.\d)?\)", with_ui["statuses"][0])
    without_ui = drive("attach", {"steps": [{"hasUI": False, "usage": {"tokens": 124000, "window": 200000, "percent": 62}}]})
    assert without_ui["statuses"] == []
