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
    assert out["rcptAfterConfirm"] is True
    assert out["rcptAtEnd"] is True


def test_swallowed_submit_retries_until_landing() -> None:
    out = drive("retry")
    assert len(out["submits"]) == 2
    assert out["rcptAfterConfirm"] is False
    assert out["rcptAtEnd"] is True


def test_already_landed_marks_delivered_without_submit() -> None:
    out = drive("prelanded")
    assert len(out["submits"]) == 1
    assert out["rcptAtEnd"] is True
