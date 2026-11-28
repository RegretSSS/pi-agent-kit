import json
import subprocess
from pathlib import Path

TESTS = Path(__file__).resolve().parent

BLOCKED = [
    "sleep 1500",
    "sleep 2700",
    "sleep 2m",
    "sleep 3h",
    "sleep 1d",
    "sleep 100.5",
    "echo start; sleep 600",
    "while :; do sleep 300; done",
    "if [ -f x ]; then sleep 300; fi",
    "/bin/sleep 300",
    "echo sleep 999",
    "echo a; echo b; sleep 600",
    "sleep 600",
    "sleep 90 90",
    "sleep 30 30 50",
    "sleep 1e3",
    "sleep .5e3",
    "sleep 1E+3",
    "sleep 2e2s",
    "sleep +300",
    "sleep inf",
    "sleep infinity",
    "sleep 60 60; echo done",
]

ALLOWED = [
    "sleep 100",
    "sleep 99",
    "sleep 0.5",
    "sleep 30 30",
    "sleep 1e-3",
    "sleep +99",
    "sleep 5.",
    "sleep 100; echo done",
    "ls -la",
    "make && make test",
    'grep -n "sleep 30" run.sh',
    "usleep 500",
    "sleepy 300",
    "echo sleep info 5",
]


def run_driver():
    proc = subprocess.run(
        ["node", str(TESTS / "no_long_sleep_driver.mjs"), json.dumps(BLOCKED + ALLOWED)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_blocks_long_sleep_including_intentional_overreach():
    result = run_driver()
    events = result["events"]
    for event in events[: len(BLOCKED)]:
        assert event["blocked"], event["command"]
        assert "task_create" in event["reason"], event["command"]
    for event in events[len(BLOCKED) :]:
        assert not event["blocked"], event["command"]


def test_blocked_call_does_not_poison_the_next_command():
    events = run_driver()["events"]
    trailing = events[BLOCKED.index("echo a; echo b; sleep 600")]
    leading = events[BLOCKED.index("sleep 600")]
    assert trailing["blocked"] and leading["blocked"]


def test_reason_reports_every_duration_and_the_total():
    events = {event["command"]: event for event in run_driver()["events"]}
    assert "90 90（180s）" in events["sleep 90 90"]["reason"]
    assert "inf（永不返回）" in events["sleep inf"]["reason"]
    assert "1E+3（1000s）" in events["sleep 1E+3"]["reason"]


def test_scopes_to_bash_tool_and_string_command():
    result = run_driver()
    assert result["otherToolBlocked"] is False
    assert result["missingCommandBlocked"] is False
    assert result["arrayCommandBlocked"] is False
