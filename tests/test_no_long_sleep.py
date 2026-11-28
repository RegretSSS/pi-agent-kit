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
]

ALLOWED = [
    "sleep 100",
    "sleep 99",
    "sleep 0.5",
    "ls -la",
    "make && make test",
    'grep -n "sleep 30" run.sh',
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


def test_scopes_to_bash_tool_and_string_command():
    result = run_driver()
    assert result["otherToolBlocked"] is False
    assert result["missingCommandBlocked"] is False
    assert result["arrayCommandBlocked"] is False
