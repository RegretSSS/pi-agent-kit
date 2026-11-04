#!/usr/bin/env python3
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDER = (
    "import { renderIndex } from \"%s/extensions/memory.ts\";\n"
    "const entries = [{ name: \"probe\", description: \"钩子\", type: \"reference\", file: \"probe.md\", body: \"x\" }];\n"
    "process.stdout.write(JSON.stringify(renderIndex(entries)));\n"
) % ROOT


def lint() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        rendered = subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", RENDER],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if rendered.returncode != 0:
            return ["agentsmd_lint_parses_renderindex_output: renderIndex 探针失败: " + rendered.stderr.strip()[:200]]
        index_text = json.loads(rendered.stdout)
        memory_dir = Path(tmp) / "memory"
        memory_dir.mkdir()
        (memory_dir / "probe.md").write_text("---\nname: probe\ndescription: 钩子\ntype: reference\n---\nx")
        (memory_dir / "MEMORY.md").write_text(index_text)

        spec = importlib.util.spec_from_file_location("idx_lint", ROOT / "lints" / "agentsmd_index_consistency.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        problems = module.lint(memory_dir)
        if problems:
            return [
                "agentsmd_lint_parses_renderindex_output: 索引一致性 lint 解析不了 renderIndex 真实产物("
                + "; ".join(problems)
                + ")—— fixture 手写格式与生产格式脱节会放行解析 bug"
            ]
        return []


if __name__ == "__main__":
    found = lint()
    for item in found:
        print(item)
    print("agentsmd_lint_parses_renderindex_output: ok" if not found else "")
    sys.exit(1 if found else 0)
