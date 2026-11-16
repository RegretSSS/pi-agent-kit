import json
import subprocess
from pathlib import Path

TESTS = Path(__file__).resolve().parent

BLOCKED = [
    "nohup python3 long.py",
    "python3 a.py; nohup b.py &",
    "setsid ./run.sh",
    "echo start && nohup x",
    "cmd & disown",
    "disown %1",
    "sleep 300 &",
    "./e2e.sh > out.log 2>&1 &",
    "env FOO=1 nohup x",
    "echo a | nohup tee log",
    "make 2>&1 | tee build.log &",
]

ALLOWED = [
    "grep nohup /var/log/x",
    "echo nohup is a word",
    'echo "&"',
    "grep ' & ' notes.txt",
    "make && make test",
    "ls -la",
    "a && b && c",
    'bash -c "echo hi"',
    "nohuped-text-reader --file x",
]


def run_driver():
    proc = subprocess.run(
        ["node", str(TESTS / "rogue_background_driver.mjs"), json.dumps(BLOCKED + ALLOWED)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_blocks_backgrounding_paths():
    result = run_driver()
    events = result["events"]
    for event in events[: len(BLOCKED)]:
        assert event["blocked"], event["command"]
        assert "task_create" in event["reason"], event["command"]
    for event in events[len(BLOCKED) :]:
        assert not event["blocked"], event["command"]


def test_scopes_to_bash_tool_and_string_command():
    result = run_driver()
    assert result["otherToolBlocked"] is False
    assert result["missingCommandBlocked"] is False
