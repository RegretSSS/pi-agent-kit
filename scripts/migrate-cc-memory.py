#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CC_ROOT = Path.home() / ".claude" / "projects"
TARGET = Path.home() / ".agents" / "memory"
VALID_TYPES = {"user", "project", "feedback", "reference"}
RULE_SHAPED = [
    re.compile(r"看到[^。\n]{1,40}就\s*(fail|拒绝|报错|禁)"),
    re.compile(r"(一律|必须|禁止|不得|不许)[^。\n]{0,40}(一律|必须|禁止|不得|不许)"),
]
SKIP_FILES = {"MEMORY.md"}


def parse_cc_memory(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fields: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        idx = line.find(":")
        if idx <= 0:
            continue
        fields[line[:idx].strip()] = line[idx + 1 :].strip().strip('"')
    name = fields.get("name")
    description = fields.get("description")
    if not name or not description:
        return None
    match = re.search(r"^  type: (\S+)$", text[4:end], re.MULTILINE)
    body = text[end + 5 :]
    return {"name": name, "description": description, "type": match.group(1) if match else None, "body": body}


def is_rule_shaped(text: str) -> bool:
    return any(pattern.search(text) for pattern in RULE_SHAPED)


def project_slug(project_dir: Path) -> str:
    tail = project_dir.name
    tail = tail.lstrip("-")
    tail = re.sub(r"[^a-zA-Z0-9_-]+", "-", tail).strip("-")
    return tail[:40] or "proj"


def collect():
    entries = []
    lints_suggestions = []
    unclassified = []
    for project_dir in sorted(CC_ROOT.glob("*/memory")):
        if not project_dir.is_dir():
            continue
        for file in sorted(project_dir.glob("*.md")):
            if file.name in SKIP_FILES:
                continue
            parsed = parse_cc_memory(file.read_text())
            if parsed is None:
                unclassified.append((project_dir.name, file.name, "frontmatter 不完整"))
                continue
            if is_rule_shaped(f"{parsed['description']}\n{parsed['body']}"):
                lints_suggestions.append((project_dir.name, file.name, parsed["name"]))
                continue
            if parsed["type"] not in VALID_TYPES:
                unclassified.append((project_dir.name, file.name, f"type={parsed['type']}"))
                continue
            entries.append((project_dir, file, parsed))
    return entries, lints_suggestions, unclassified


def plan(entries):
    taken = set()
    actions = []
    for project_dir, file, parsed in entries:
        name = parsed["name"]
        if name in taken:
            name = f"{name}-{project_slug(project_dir)}"
            suffix = 2
            while name in taken:
                name = f"{parsed['name']}-{project_slug(project_dir)}-{suffix}"
                suffix += 1
        taken.add(name)
        actions.append({"project": project_dir.name, "source": str(file), **parsed, "orig_name": parsed["name"], "name": name})
    return actions


def render_md(action, migrate_note):
    lines = ["---", f"name: {action['name']}", f"description: {action['description']}", f"type: {action['type']}"]
    if action["type"] == "project":
        expiry = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        lines.append(f"expiry_at: {expiry}")
    lines.append("---", "")
    body = action["body"].rstrip("\n")
    lines.append(body)
    lines.append("")
    lines.append(migrate_note)
    return "\n".join(lines) + "\n"


def rebuild_target_index(target: Path) -> None:
    probe = (
        f'import {{ MemoryStore }} from "{REPO}/extensions/memory.ts";'
        f"const store = new MemoryStore({json.dumps(str(target))});"
        "await store.rebuildIndex();"
        "store.close();"
    )
    subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", probe],
        check=True,
        cwd=REPO,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="CC per-project memory → 全局 ~/.agents/memory 四分流迁移(默认 dry-run)")
    parser.add_argument("--apply", action="store_true", help="实际写入目标目录并重建索引")
    args = parser.parse_args()

    entries, lints_suggestions, unclassified = collect()
    actions = plan(entries)
    migrate_note = f"> migrated from Claude Code memory @ {datetime.now().strftime('%Y-%m-%d')}"

    print(f"扫描 {CC_ROOT}:可迁移 {len(actions)} 条,建议进 lints {len(lints_suggestions)} 条,需人工分流 {len(unclassified)} 条")
    for project, file, name in lints_suggestions[:20]:
        print(f"  [lints 候选] {project}/{file} (name={name})")
    for project, file, reason in unclassified[:20]:
        print(f"  [人工分流] {project}/{file}: {reason}")
    renamed = sum(1 for a in actions if a["name"] != a["orig_name"])
    print(f"同名冲突改名 {renamed} 条")
    for action in actions[:10]:
        print(f"  {action['type']:9s} {action['name']} ← {action['project']}")
    if len(actions) > 10:
        print(f"  … 共 {len(actions)} 条")

    if not args.apply:
        print("dry-run 完成;加 --apply 执行写入")
        return 0

    TARGET.mkdir(parents=True, exist_ok=True)
    for action in actions:
        (TARGET / f"{action['name']}.md").write_text(render_md(action, migrate_note))
    rebuild_target_index(TARGET)
    print(f"已写入 {TARGET} 并重建 MEMORY.md + FTS 索引")
    return 0


if __name__ == "__main__":
    sys.exit(main())
