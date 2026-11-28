import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "quiet_tui_driver.mjs"


def pure() -> dict:
    if shutil.which("node") is None:
        pytest.skip("无 node")
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(DRIVER), "pure"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-800:]
    return json.loads(result.stdout)["pure"]


def test_sanitize_strips_sequences_and_folds_whitespace():
    assert pure()["sanitize"] == ["ab c defg", "x y"]


def test_compact_args_quotes_blank_bearing_strings_and_caps_values():
    compact = pure()["compact"]
    assert compact[0] == 'cmd="sleep 4; echo X" name=bg-e2e'
    assert compact[1].startswith('nested={"a":1} list=[1,2] long=' + "x" * 59 + "…")
    assert compact[2:] == ["scalar", '[1,"a b"]']


def test_format_duration_boundaries():
    assert pure()["duration"] == ["0.0s", "1.2s", "59.9s", "1m 0s", "1m 0s", "1m 30s", "1h 0m", "1h 0m", "2h 0m", "2h 1m"]


def test_takes_over_builtins_mcp_and_rendererless_tools_only():
    assert pure()["takesOver"] == [
        ["bash", True],
        ["codemode", True],
        ["mcp__x__y", True],
        ["task_create", True],
        ["task_create", True],
        ["Agent", False],
        ["custom", False],
        ["custom", False],
    ]


def test_labels():
    assert pure()["mcp"] == "docs/search"
    assert pure()["path"] == "~/x/y"


def test_builtin_roster():
    assert pure()["builtins"] == ["bash", "powershell", "read", "edit", "write", "grep", "find", "ls", "codemode"]


def test_script_summary_skips_the_options_line_and_blank_rows():
    assert pure()["script"] == [["const a = 1;", "  const b = 2;"], ["body"], [], ["{ not code"], []]


def test_nested_call_progress_names_the_latest_call_and_counts_failures():
    assert pure()["progress"] == [
        "",
        "1 call · … read",
        "2 calls · ✗ grep 1.2s · 1 failed",
        "1 call · ⊘ write",
        "2 calls · … ?",
        "1 call · ✓ models.classify 1m 5s",
    ]


def test_codemode_failure_drops_the_script_headers():
    assert pure()["failure"] == ["TypeError: rows is not iterable", 'Invalid options: unknown key "foo"', "", ""]
