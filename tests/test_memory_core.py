import json
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "tests" / "memory_core_driver.mjs"


def drive(root: Path, scenario: str, payload: dict | None = None) -> dict:
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(DRIVER), str(root), scenario, json.dumps(payload or {}, ensure_ascii=False)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_save_rebuilds_index(tmp_path) -> None:
    out = drive(tmp_path, "save", {"name": "aliyun-ops", "description": "阿里云 cli 运维口径", "type": "reference", "body": "profile=claude-admin, region=cn-beijing"})
    assert out["outcome"]["status"] == "saved"
    drive(tmp_path, "save", {"name": "compact-tool", "description": "pi 会话压缩工具", "type": "user", "body": "compact 工具在 turn 边界压缩"})
    memory_md = (tmp_path / "MEMORY.md").read_text()
    assert "- [aliyun-ops](aliyun-ops.md) — 阿里云 cli 运维口径" in memory_md
    assert "- [compact-tool](compact-tool.md) — pi 会话压缩工具" in memory_md
    state = drive(tmp_path, "index")
    assert "[reference] aliyun-ops — 阿里云 cli 运维口径" in state["index"]
    assert len(state["entries"]) == 2


def test_duplicate_rejected_and_update_path(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "aliyun-ops", "description": "阿里云 cli 运维口径", "type": "reference", "body": "x"})
    dup = drive(tmp_path, "save", {"name": "aliyun-ops-2", "description": "阿里云 cli 运维口径补充", "type": "reference", "body": "y"})
    assert dup["outcome"]["status"] == "rejected-duplicate"
    assert "aliyun-ops" in dup["outcome"]["hits"]
    update = drive(tmp_path, "save", {"name": "aliyun-ops", "description": "阿里云 cli 运维口径 v2", "type": "reference", "body": "z"})
    assert update["outcome"]["status"] == "saved"
    assert update["outcome"]["updated"] is True
    assert len(drive(tmp_path, "index")["entries"]) == 1


def test_rule_shaped_and_problem_rejected(tmp_path) -> None:
    problem = drive(tmp_path, "save", {"name": "deadlock", "description": "死锁", "type": "problem", "body": "x"})
    assert problem["outcome"]["status"] == "rejected-lints"
    shaped = drive(tmp_path, "save", {"name": "rule-ish", "description": "规则", "type": "feedback", "body": "看到 rm -rf 就拒绝执行,一律必须先确认"})
    assert shaped["outcome"]["status"] == "rejected-lints"
    assert "lints" in shaped["outcome"]["message"]
    assert drive(tmp_path, "index")["entries"] == []


def test_search_chinese_and_substring(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "aliyun-ops", "description": "阿里云 cli 口径", "type": "reference", "body": "profile=claude-admin,运维口径:region cn-beijing"})
    drive(tmp_path, "save", {"name": "compact-tool", "description": "pi 会话压缩工具", "type": "user", "body": "compact 工具"})
    assert drive(tmp_path, "search", {"query": "运维口径"})["names"] == ["aliyun-ops"]
    assert drive(tmp_path, "search", {"query": "aliyun"})["names"] == ["aliyun-ops"]
    assert drive(tmp_path, "search", {"query": "ompa"})["names"] == ["compact-tool"]


def test_project_expiry_and_archive_candidate(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "engprime-ops", "description": "判卷运维项目", "type": "project", "body": "进行中"})
    entries = drive(tmp_path, "index")["entries"]
    assert entries[0]["expiryAt"] is not None

    fresh = drive(tmp_path, "save", {"name": "fresh-project", "description": "新项目", "type": "project", "body": "y"})
    assert fresh["outcome"]["status"] == "saved"
    assert drive(tmp_path, "archive-scan", {"name": "fresh-project", "lastReferenced": 0})["promoted"] == []

    drive(tmp_path, "backdate", {"name": "engprime-ops"})
    unreferenced = drive(tmp_path, "archive-scan", {"name": "engprime-ops", "lastReferenced": 0})
    assert unreferenced["promoted"] == ["engprime-ops"]
    state = drive(tmp_path, "index")
    marked = [e for e in state["entries"] if e["name"] == "engprime-ops"][0]
    assert marked["archiveCandidate"] is True
    assert "(archive-candidate)" in (tmp_path / "MEMORY.md").read_text()

    drive(tmp_path, "save", {"name": "other-project", "description": "另一项目", "type": "project", "body": "z"})
    drive(tmp_path, "backdate", {"name": "other-project"})
    referenced = drive(tmp_path, "archive-scan", {"name": "other-project", "lastReferenced": int(time.time() * 1000)})
    assert referenced["promoted"] == []


def test_kebab_fts_query_no_syntax_error(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "aliyun-ops", "description": "阿里云口径", "type": "reference", "body": "x"})
    out = drive(tmp_path, "search", {"query": "aliyun-ops"})
    assert out["names"] == ["aliyun-ops"]


def test_candidates_append(tmp_path) -> None:
    drive(tmp_path, "candidates")
    lines = (tmp_path / ".candidates.jsonl").read_text().strip().split("\n")
    assert json.loads(lines[-1]) == {"probe": True}


def test_candidates_rotate_at_5mb(tmp_path) -> None:
    out = drive(tmp_path, "candidates-rotate")
    assert out["rotated"] is True
    assert json.loads(out["fresh"]) == {"after": "rotate"}


def test_single_term_overlap_not_rejected(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "engprime-ops", "description": "engprime 定时任务口径", "type": "reference", "body": "x"})
    near = drive(tmp_path, "save", {"name": "engprime-jobs", "description": "engprime 任务队列", "type": "reference", "body": "y"})
    assert near["outcome"]["status"] == "saved"
    assert len(drive(tmp_path, "index")["entries"]) == 2


def test_variant_name_and_desc_duplicate_rejected(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "duo-cache-probe", "description": "双会话缓存探针", "type": "reference", "body": "x"})
    variant = drive(tmp_path, "save", {"name": "duo-cache-probe-v2", "description": "双会话缓存探针 补充", "type": "reference", "body": "y"})
    assert variant["outcome"]["status"] == "rejected-duplicate"
    assert variant["outcome"]["hits"] == ["duo-cache-probe"]


def test_multiline_description_rejected(tmp_path) -> None:
    smuggled = drive(tmp_path, "save", {"name": "multi-desc", "description": "first\n---\nsmuggled: yes", "type": "reference", "body": "x"})
    assert smuggled["outcome"]["status"] == "rejected-lints"
    plain = drive(tmp_path, "save", {"name": "plain-desc", "description": "hook\nsecond line", "type": "reference", "body": "x"})
    assert plain["outcome"]["status"] == "rejected-lints"
    assert drive(tmp_path, "index")["entries"] == []


def test_memory_reserved_name_rejected(tmp_path) -> None:
    out = drive(tmp_path, "save", {"name": "MEMORY", "description": "撞索引", "type": "reference", "body": "x"})
    assert out["outcome"]["status"] == "rejected-lints"
    assert drive(tmp_path, "index")["entries"] == []


def test_context_index_capped_and_lossless_pointer(tmp_path) -> None:
    out = drive(tmp_path, "render-context")
    assert "共 35 条" in out["rendered"]
    assert "其余 5 条略" in out["rendered"]
    assert "memory_search" in out["rendered"]
    rows = [line for line in out["rendered"].split("\n") if line.startswith("- [")]
    assert len(rows) == 30
