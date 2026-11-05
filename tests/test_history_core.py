import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "history_core_driver.mjs"


def drive(root: Path, scenario: str, payload: dict | None = None) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), str(root), scenario, json.dumps(payload or {}, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_seed_builds_sidecar(tmp_path) -> None:
    out = drive(tmp_path, "seed")
    assert out["refreshed"] is True
    assert out["available"] is True
    snapshots = list((tmp_path / "sidecar").glob("sidecar.*.jsonl"))
    assert len(snapshots) == 1
    lines = snapshots[0].read_text().strip().split("\n")
    assert len(lines) == 5
    first = json.loads(lines[0])
    assert first["topic"] == "整理ClaudeCode记忆入memory系统"
    assert first["tokens"] == 55647
    assert first["active"] is True


def test_search_hits_and_ranks(tmp_path) -> None:
    drive(tmp_path, "seed")
    out = drive(tmp_path, "search", {"query": "民法典 重灌"})
    assert len(out["hits"]) >= 2
    out_session = drive(tmp_path, "search", {"query": "民法典", "session": "01a1a94b"})
    assert {h["session"] for h in out_session["hits"]} == {"01a1a94b-7621"}
    assert out_session["hits"][0]["active"] is False


def test_search_cjk_unspaced_falls_back_to_bigrams(tmp_path) -> None:
    drive(tmp_path, "seed")
    out = drive(tmp_path, "search-bigram")
    assert "b1" in out["hits"] or "b2" in out["hits"]


def test_outline_respects_budget(tmp_path) -> None:
    out = drive(tmp_path, "outline-budget")
    assert out["length"] <= 900
    assert out["truncated"] >= 15


def test_read_block_full_window_and_guard(tmp_path) -> None:
    drive(tmp_path, "seed")
    full = drive(tmp_path, "read", {"session": "01a1a774", "block": "b1"})
    assert full["status"] == "ok"
    assert "整理" in full["text"]
    window = drive(tmp_path, "read", {"session": "01a1a94b", "block": "b2", "around": "A10"})
    assert window["status"] == "ok"
    assert "A10" in window["text"]
    missing = drive(tmp_path, "read", {"session": "01a1a94b", "block": "b99"})
    assert missing["status"] == "missing"


def test_read_sibling_prefix_is_ambiguous(tmp_path) -> None:
    drive(tmp_path, "seed")
    amb = drive(tmp_path, "read", {"session": "01a1a784", "block": "b1"})
    assert amb["status"] == "ambiguous"
    assert {c["session"] for c in amb["candidates"]} == {"01a1a784-b231", "01a1a784-b23c"}
    short = drive(tmp_path, "read", {"session": "0", "block": "b1"})
    assert short["status"] == "invalid-session"
    exact = drive(tmp_path, "read", {"session": "01a1a784-b23c", "block": "b1"})
    assert exact["status"] == "ok"
    assert exact["session"] == "01a1a784-b23c"
    assert "docs" in exact["text"]


def test_execute_search_details_are_full_and_budgeted(tmp_path) -> None:
    drive(tmp_path, "seed")
    out = drive(tmp_path, "execute-search", {"query": "民法典"})
    assert out["textHead"].startswith("2 block(s) match:") or "block(s) match" in out["textHead"]
    assert all(len(h["session"]) == 13 for h in out["hits"])
    assert all(h["topicLen"] <= 80 for h in out["hits"])


def test_execute_search_limit_clamped(tmp_path) -> None:
    drive(tmp_path, "seed-big")
    out = drive(tmp_path, "execute-search", {"query": "民法典", "limit": 99})
    assert len(out["hits"]) == 10


def test_execute_read_surfaces_ambiguity_and_inactive(tmp_path) -> None:
    drive(tmp_path, "seed")
    amb = drive(tmp_path, "execute-read", {"session": "01a1a784", "block": "b1"})
    assert amb["isError"] is True
    assert "前缀歧义" in amb["head"]
    assert len(amb["details"]["candidates"]) == 2
    inactive = drive(tmp_path, "execute-read", {"session": "01a1a94b", "block": "b2"})
    assert inactive["isError"] is False
    assert inactive["details"]["active"] is False


def test_execute_unavailable_message(tmp_path) -> None:
    out = drive(tmp_path, "execute-unavailable")
    assert out["available"] is False
    assert "unavailable" in out["text"]


def test_empty_table_never_overwrites_sidecar(tmp_path) -> None:
    out = drive(tmp_path, "empty-table")
    assert out["refreshed"] is True
    assert out["available"] is True
    assert out["sidecarUnchanged"] is True


def test_stale_sidecar_survives_db_removal(tmp_path) -> None:
    drive(tmp_path, "seed")
    out = drive(tmp_path, "stale")
    assert out["available"] is True
    assert len(out["hits"]) >= 2


def test_unavailable_reports_false(tmp_path) -> None:
    out = drive(tmp_path, "unavailable")
    assert out["refreshed"] is False
    assert out["available"] is False


def test_compact_instructions_fold_index(tmp_path) -> None:
    with_history = drive(tmp_path, "instructions", {"brief": "keep task state", "historyActive": True})
    assert with_history["text"].startswith("keep task state")
    assert "<fold-index>" in with_history["text"]
    assert 'trace: history_search("' in with_history["text"]
    assert "at most one fold-index stays alive" in with_history["text"]
    without = drive(tmp_path, "instructions", {"brief": "keep task state", "historyActive": False})
    assert "history_search" not in without["text"]
    assert "<fold-index>" in without["text"]


def test_execute_search_reports_source(tmp_path) -> None:
    drive(tmp_path, "seed")
    out = drive(tmp_path, "execute-search", {"query": "民法典"})
    assert out["source"] == "db"


def test_stale_sidecar_reports_source(tmp_path) -> None:
    drive(tmp_path, "seed")
    out = drive(tmp_path, "stale")
    assert out["available"] is True
    assert out["source"] == "sidecar"


def test_persist_failure_still_serves_fresh_db(tmp_path) -> None:
    out = drive(tmp_path, "persist-fail")
    assert out["refreshed"] is True
    assert out["available"] is True
    assert out["source"] == "db"
    assert len(out["hits"]) >= 2


def test_gc_shrink_leaves_no_ghost_blocks(tmp_path) -> None:
    out = drive(tmp_path, "shrink")
    assert out["refreshed"] is True
    assert out["source"] == "sidecar"
    assert out["sessions"] == ["01a1a94b-7621"]
    assert all(not s.startswith(("01a1a77", "01a1a78")) for s in out["sessions"])


def test_readonly_sidecar_dir_never_spins(tmp_path) -> None:
    out = drive(tmp_path, "ro-sidecar")
    assert out["refreshed"] is True
    assert out["elapsedMs"] < 5000
    assert out["available"] is True
    assert out["source"] == "db"
    assert len(out["hits"]) >= 2


def test_fallback_reads_newest_snapshot(tmp_path) -> None:
    out = drive(tmp_path, "multi-snapshot")
    assert out["refreshed"] is True
    assert out["source"] == "sidecar"
    assert out["sessions"] == ["s-new"]
