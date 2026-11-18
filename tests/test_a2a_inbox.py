import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "a2a_inbox_driver.mjs"


def drive(scenario: str) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), scenario],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_landed_wake_confirmed_by_rcpt() -> None:
    out = drive("deliver")
    assert len(out["submits"]) == 1
    assert out["submits"][0]["options"] == {"deliverAs": "steer"}
    assert out["rcptAtEnd"] is True


def test_landing_unseen_never_reinjects() -> None:
    out = drive("storm")
    assert len(out["submits"]) == 1
    assert out["rcptAtEnd"] is False
    assert out["claimAtEnd"] is True


def test_submit_throw_releases_claim_and_retries() -> None:
    out = drive("throw-release")
    assert out["throws"] == 1
    assert len(out["submits"]) == 1
    assert out["rcptAtEnd"] is True


def test_foreign_claim_blocks_injection() -> None:
    out = drive("foreign-claim")
    assert len(out["submits"]) == 0
    assert out["rcptAtEnd"] is False


def test_stale_claim_reclaimed_and_injected() -> None:
    out = drive("stale-claim")
    assert len(out["submits"]) == 1
    assert out["rcptAtEnd"] is True


def test_already_landed_marks_delivered_without_second_submit() -> None:
    out = drive("prelanded")
    assert len(out["submits"]) == 1
    assert out["rcptAtEnd"] is True
