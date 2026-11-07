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


def test_rewritten_desc_variant_still_rejected(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "deploy-keys", "description": "发布用凭据口径", "type": "reference", "body": "x"})
    rewritten = drive(tmp_path, "save", {"name": "deploy-keys-v2", "description": "完全换写的钩子文案", "type": "reference", "body": "y"})
    assert rewritten["outcome"]["status"] == "rejected-duplicate"


def test_case_and_nfc_variants_rejected(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "Deploy-Keys", "description": "d1", "type": "reference", "body": "x"})
    lower = drive(tmp_path, "save", {"name": "deploy-keys", "description": "d2", "type": "reference", "body": "y"})
    assert lower["outcome"]["status"] == "saved"
    assert lower["outcome"]["updated"] is True
    assert len(drive(tmp_path, "index")["entries"]) == 1


def test_blank_description_rejected(tmp_path) -> None:
    blank = drive(tmp_path, "save", {"name": "blank-desc", "description": "   ", "type": "reference", "body": "x"})
    control = drive(tmp_path, "save", {"name": "ctrl-desc", "description": "\x07\x1b", "type": "reference", "body": "x"})
    assert blank["outcome"]["status"] == "rejected-lints"
    assert control["outcome"]["status"] == "rejected-lints"
    assert drive(tmp_path, "index")["entries"] == []


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


def test_append_mode_merges_into_existing(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "bili-ops", "description": "压缩代理口径", "type": "reference", "body": "代理 127.0.0.1:18787"})
    out = drive(tmp_path, "save", {"name": "bili-ops", "description": "压缩代理口径", "type": "reference", "body": "db 在 ~/.local/share/billion-context/", "mode": "append"})
    assert out["outcome"]["status"] == "saved"
    assert out["outcome"]["updated"] is True
    assert out["outcome"]["merged"] == "appended"
    body = drive(tmp_path, "read", {"name": "bili-ops"})["body"]
    assert "127.0.0.1:18787" in body
    assert "db 在 ~/.local/share/billion-context/" in body
    assert body.index("18787") < body.index("billion-context")


def test_append_on_missing_name_creates_with_dup_gate(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "bili-ops", "description": "压缩代理口径", "type": "reference", "body": "x"})
    dup = drive(tmp_path, "save", {"name": "bili-ops-2", "description": "压缩代理口径补充", "type": "reference", "body": "y", "mode": "append"})
    assert dup["outcome"]["status"] == "rejected-duplicate"
    fresh = drive(tmp_path, "save", {"name": "magpie-ops", "description": "路由网关口径", "type": "reference", "body": "首段", "mode": "append"})
    assert fresh["outcome"]["status"] == "saved"
    assert fresh["outcome"]["updated"] is False
    assert drive(tmp_path, "read", {"name": "magpie-ops"})["body"].strip() == "首段"


def test_section_replace_and_add(tmp_path) -> None:
    body = "前言行\n\n## 环境\n\n旧环境段\n\n## 排障\n\n排障段"
    drive(tmp_path, "save", {"name": "bili-ops", "description": "压缩代理口径", "type": "reference", "body": body})
    out = drive(tmp_path, "save", {"name": "bili-ops", "description": "压缩代理口径", "type": "reference", "body": "新环境段", "section": "环境"})
    assert out["outcome"]["merged"] == "section"
    merged = drive(tmp_path, "read", {"name": "bili-ops"})["body"]
    assert "新环境段" in merged
    assert "旧环境段" not in merged
    assert "排障段" in merged
    assert "前言行" in merged
    added = drive(tmp_path, "save", {"name": "bili-ops", "description": "压缩代理口径", "type": "reference", "body": "全新小节段", "section": "升级"})
    assert added["outcome"]["merged"] == "section"
    merged = drive(tmp_path, "read", {"name": "bili-ops"})["body"]
    assert "## 升级\n\n全新小节段" in merged
    assert merged.index("升级") > merged.index("排障")


def test_section_ignores_fenced_headings(tmp_path) -> None:
    body = "```\n## 块内节\n不该被动\n```\n\n## 真节\n\n真节内容"
    drive(tmp_path, "save", {"name": "deploy-notes", "description": "部署口径", "type": "reference", "body": body})
    drive(tmp_path, "save", {"name": "deploy-notes", "description": "部署口径", "type": "reference", "body": "换新内容", "section": "真节"})
    merged = drive(tmp_path, "read", {"name": "deploy-notes"})["body"]
    assert "## 块内节" in merged
    assert "不该被动" in merged
    assert "换新内容" in merged
    fenced = drive(tmp_path, "save", {"name": "deploy-notes", "description": "部署口径", "type": "reference", "body": "目标", "section": "块内节"})
    assert fenced["outcome"]["status"] == "saved"
    merged = drive(tmp_path, "read", {"name": "deploy-notes"})["body"]
    assert "不该被动" in merged
    assert "## 块内节\n\n目标" in merged


def test_section_on_missing_name_creates_wrapped(tmp_path) -> None:
    out = drive(tmp_path, "save", {"name": "new-entry", "description": "d", "type": "reference", "body": "首节内容", "section": "环境"})
    assert out["outcome"]["status"] == "saved"
    assert out["outcome"]["updated"] is False
    body = drive(tmp_path, "read", {"name": "new-entry"})["body"]
    assert body.strip() == "## 环境\n\n首节内容"


def test_repeated_append_never_accumulates_blank_lines(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "bili-ops", "description": "d", "type": "reference", "body": "第1段"})
    for i in range(4):
        drive(tmp_path, "save", {"name": "bili-ops", "description": "d", "type": "reference", "body": f"第{i + 2}段", "mode": "append"})
    body = drive(tmp_path, "read", {"name": "bili-ops"})["body"]
    assert body.count("\n\n\n") == 0
    assert all(f"第{i}段" in body for i in range(1, 6))


def test_section_and_mode_validation(tmp_path) -> None:
    conflict = drive(tmp_path, "save", {"name": "x-ops", "description": "d", "type": "reference", "body": "b", "mode": "append", "section": "s"})
    assert conflict["outcome"]["status"] == "rejected-lints"
    for bad in ["", "   ", "#标题", "a" * 65]:
        rejected = drive(tmp_path, "save", {"name": "x-ops", "description": "d", "type": "reference", "body": "b", "section": bad})
        assert rejected["outcome"]["status"] == "rejected-lints"
    bad_mode = drive(tmp_path, "save", {"name": "x-ops", "description": "d", "type": "reference", "body": "b", "mode": "merge"})
    assert bad_mode["outcome"]["status"] == "rejected-lints"
    assert drive(tmp_path, "index")["entries"] == []


def test_incremental_refreshes_index_description(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "bili-ops", "description": "旧钩子", "type": "reference", "body": "x"})
    drive(tmp_path, "save", {"name": "bili-ops", "description": "新钩子", "type": "reference", "body": "y", "mode": "append"})
    assert "- [bili-ops](bili-ops.md) — 新钩子" in (tmp_path / "MEMORY.md").read_text()


def test_append_clears_archive_candidate_and_renews_ttl(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "eng-ops", "description": "项目口径", "type": "project", "body": "进行中"})
    drive(tmp_path, "backdate", {"name": "eng-ops"})
    assert drive(tmp_path, "archive-scan", {"name": "eng-ops", "lastReferenced": 0})["promoted"] == ["eng-ops"]
    out = drive(tmp_path, "save", {"name": "eng-ops", "description": "项目口径", "type": "project", "body": "追加段", "mode": "append"})
    assert out["outcome"]["status"] == "saved"
    state = drive(tmp_path, "index")
    entry = [e for e in state["entries"] if e["name"] == "eng-ops"][0]
    assert entry["archiveCandidate"] is False
    assert entry["expiryAt"] > "2026-"


def test_project_root_encoding(tmp_path) -> None:
    out = drive(tmp_path, "project-root", {"cwd": "/home/remedy/workspace/aicontest-clinical-note"})
    assert out["root"] == str(tmp_path / "projects" / "-home-remedy-workspace-aicontest-clinical-note")
    weird = drive(tmp_path, "project-root", {"cwd": "/mnt/d/000-自制软件/建筑信源"})
    assert weird["root"].endswith("-mnt-d-000----------")


def test_scoped_save_routes_and_gates(tmp_path) -> None:
    project_root = tmp_path / "projects" / "-w-proj"
    out = drive(tmp_path, "scoped", {"action": "save", "projectRoot": str(project_root), "name": "deploy-port", "description": "本仓部署端口", "type": "project", "body": "端口 8899"})
    assert out["outcome"]["status"] == "saved"
    assert (project_root / "deploy-port.md").exists() and not (tmp_path / "deploy-port.md").exists()
    out = drive(tmp_path, "scoped", {"action": "save", "projectRoot": str(project_root), "name": "aliyun-cli", "description": "阿里云 cli 运维口径", "type": "reference", "body": "profile=claude-admin", "scope": "global"})
    assert out["outcome"]["status"] == "saved"
    assert (tmp_path / "aliyun-cli.md").exists() and not (project_root / "aliyun-cli.md").exists()
    rejected = drive(tmp_path, "scoped", {"action": "save", "projectRoot": str(project_root), "name": "proj-only", "description": "项目认知", "type": "project", "body": "x", "scope": "global"})
    assert rejected["outcome"]["status"] == "rejected-lints"
    assert "scope=project" in rejected["outcome"]["message"]


def test_scoped_search_mixed_and_scoped(tmp_path) -> None:
    project_root = tmp_path / "projects" / "-w-proj"
    drive(tmp_path, "scoped", {"action": "save", "projectRoot": str(project_root), "name": "aliyun-cli", "description": "阿里云 cli 运维口径", "type": "reference", "body": "profile=claude-admin", "scope": "global"})
    drive(tmp_path, "scoped", {"action": "save", "projectRoot": str(project_root), "name": "deploy-port", "description": "本仓部署端口", "type": "project", "body": "端口 8899"})
    mixed = drive(tmp_path, "scoped", {"action": "search", "projectRoot": str(project_root), "query": "部署端口 阿里云"})
    scopes = {h["name"]: h["scope"] for h in mixed["hits"]}
    assert scopes.get("deploy-port") == "project"
    assert scopes.get("aliyun-cli") == "global"
    only_project = drive(tmp_path, "scoped", {"action": "search", "projectRoot": str(project_root), "query": "部署端口", "scope": "project"})
    assert [h["name"] for h in only_project["hits"]] == ["deploy-port"]
    only_global = drive(tmp_path, "scoped", {"action": "search", "projectRoot": str(project_root), "query": "部署端口 阿里云", "scope": "global"})
    assert [h["name"] for h in only_global["hits"]] == ["aliyun-cli"]


def test_scoped_search_empty_project_bucket(tmp_path) -> None:
    project_root = tmp_path / "projects" / "-w-other"
    drive(tmp_path, "save", {"name": "aliyun-cli", "description": "阿里云 cli 运维口径", "type": "reference", "body": "x"})
    out = drive(tmp_path, "scoped", {"action": "search", "projectRoot": str(project_root), "query": "阿里云"})
    assert [h["name"] for h in out["hits"]] == ["aliyun-cli"]
    assert not project_root.exists()


def test_merged_context_labels(tmp_path) -> None:
    project_root = tmp_path / "projects" / "-w-proj"
    drive(tmp_path, "scoped", {"action": "save", "projectRoot": str(project_root), "name": "aliyun-cli", "description": "阿里云 cli 运维口径", "type": "reference", "body": "x", "scope": "global"})
    drive(tmp_path, "scoped", {"action": "save", "projectRoot": str(project_root), "name": "deploy-port", "description": "本仓部署端口", "type": "project", "body": "y"})
    out = drive(tmp_path, "scoped", {"action": "context", "projectRoot": str(project_root)})
    assert "全局 1 条 + 本项目 1 条" in out["text"]
    assert "- [global] [reference] aliyun-cli" in out["text"]
    assert "- [project] [project] deploy-port" in out["text"]


def test_merged_context_missing_project_bucket_no_throw(tmp_path) -> None:
    drive(tmp_path, "save", {"name": "g1", "description": "全局条目", "type": "reference", "body": "x"})
    missing = tmp_path / "projects" / "-w-aicontest"
    out = drive(tmp_path, "scoped", {"action": "context", "projectRoot": str(missing)})
    assert "全局 1 条 + 本项目 0 条" in out["text"]
    assert "- [global] [reference] g1" in out["text"]
    assert not missing.exists()
