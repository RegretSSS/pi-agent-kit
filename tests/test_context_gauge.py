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


def usage(tokens: int, pct: int, window: int = 200000) -> dict:
    return {"usage": {"tokens": tokens, "window": window, "percent": pct}}


def test_gauge_line_tiers_with_clock() -> None:
    normal = drive("line", {"tokens": 48000, "contextWindow": 200000})["line"]
    assert re.fullmatch(r"\[ctx 24% 48k/200k" + CLOCK_RE, normal)
    warn = drive("line", {"tokens": 66000, "contextWindow": 200000})["line"]
    assert warn.startswith("[ctx 33% 66k/200k")
    assert "水位已高" in warn
    assert re.search(CLOCK_RE, warn)
    urgent = drive("line", {"tokens": 104000, "contextWindow": 200000})["line"]
    assert urgent.startswith("[ctx 52% 104k/200k")
    assert "立刻用 compact 压缩自己" in urgent
    assert re.search(CLOCK_RE, urgent)


def test_first_result_reports_then_throttled() -> None:
    out = drive("attach", {"steps": [
        usage(40000, 20),
        usage(41000, 20),
    ]})
    assert re.fullmatch(r"\[ctx 20% 40k/200k" + CLOCK_RE, out["results"][0]["appended"])
    assert out["results"][1]["appended"] is None


def test_pct_bucket_cross_reports() -> None:
    out = drive("attach", {"steps": [
        usage(40000, 20),
        usage(41000, 20),
        usage(50000, 25),
    ]})
    assert out["results"][0]["appended"] is not None
    assert out["results"][1]["appended"] is None
    assert out["results"][2]["appended"] is not None


def test_high_water_reports_every_tool() -> None:
    out = drive("attach", {"steps": [
        usage(104000, 52),
        usage(106000, 53),
    ]})
    assert out["results"][0]["appended"] is not None
    assert out["results"][1]["appended"] is not None
    assert "立刻用 compact 压缩自己" in out["results"][1]["appended"]


def test_compact_resets_throttle() -> None:
    out = drive("attach", {"steps": [
        usage(49000, 24),
        {"compact": True},
        usage(50000, 25),
    ]})
    assert out["results"][0]["appended"] is not None
    assert re.fullmatch(r"\[ctx 25% 50k/200k" + CLOCK_RE, out["results"][1]["appended"])


def test_error_result_also_reported() -> None:
    out = drive("attach", {"steps": [{"isError": True, **usage(40000, 20)}]})
    assert re.fullmatch(r"\[ctx 20% 40k/200k" + CLOCK_RE, out["results"][0]["appended"])


def test_unknown_usage_no_attach() -> None:
    out = drive("attach", {"steps": [{"usage": None}, usage(40000, 20)]})
    assert out["results"][0]["appended"] is None
    assert re.fullmatch(r"\[ctx 20% 40k/200k" + CLOCK_RE, out["results"][1]["appended"])


def test_structured_content_preserved() -> None:
    out = drive("attach", {"steps": [
        {"structuredContent": {"rows": 3}, **usage(40000, 20)},
        usage(41000, 20),
    ]})
    assert out["results"][0]["structuredContent"] == {"rows": 3}
    assert out["results"][1]["structuredContent"] is None


def test_footer_status_only_with_ui() -> None:
    with_ui = drive("attach", {"steps": [{"hasUI": True, **usage(40000, 20)}, {"hasUI": True, **usage(41000, 20)}]})
    assert len(with_ui["statuses"]) == 2
    assert re.fullmatch(r"ctx 20% 40k/200k \| \d{4}-\d{2}-\d{2} \d{2}:\d{2} 周[一二三四五六日]\(UTC[+-]\d+(?:\.\d)?\)", with_ui["statuses"][0])
    without_ui = drive("attach", {"steps": [{"hasUI": False, **usage(40000, 20)}]})
    assert without_ui["statuses"] == []
