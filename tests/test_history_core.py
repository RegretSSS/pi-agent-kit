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
    assert (tmp_path / "sidecar" / "sidecar.jsonl").exists()
    lines = (tmp_path / "sidecar" / "sidecar.jsonl").read_text().strip().split("\n")
    assert len(lines) == 4
    first = json.loads(lines[0])
    assert first["topic"] == "整理ClaudeCode记忆入memory系统"
    assert first["tokens"] == 55647


def test_search_hits_and_ranks(tmp_path) -> None:
    drive(tmp_path, "seed")
    out = drive(tmp_path, "search", {"query": "民法典 重灌"})
    assert len(out["hits"]) >= 2
    assert all("民法典" in h["hitTerms"] or "重灌" in h["hitTerms"] for h in out["hits"])
    out_session = drive(tmp_path, "search", {"query": "民法典", "session": "01a1a94b"})
    assert {h["session"] for h in out_session["hits"]} == {"01a1a94b-7621"}


def test_search_cjk_unspaced_falls_back_to_bigrams(tmp_path) -> None:
    drive(tmp_path, "seed")
    out = drive(tmp_path, "search-bigram")
    assert set(out["hits"]) >= {"b2"}


def test_outline_respects_budget(tmp_path) -> None:
    out = drive(tmp_path, "outline-budget")
    assert out["length"] <= 4200
    assert out["truncated"] >= 2


def test_read_block_full_and_window(tmp_path) -> None:
    drive(tmp_path, "seed")
    full = drive(tmp_path, "read", {"session": "01a1a774", "block": "b1"})
    assert full["isNull"] is False
    assert "整理" in full["text"]
    window = drive(tmp_path, "read", {"session": "01a1a94b", "block": "b2", "around": "A10"})
    assert "A10" in window["text"]
    assert len(window["text"]) < 400
    missing = drive(tmp_path, "read", {"session": "01a1a94b", "block": "b99"})
    assert missing["isNull"] is True


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
