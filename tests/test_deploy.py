import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNIPPET = REPO / "agents-md" / "snippet.md"


def run_deploy(home: Path) -> str:
    return subprocess.run(
        [str(REPO / "deploy.sh")],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_creates_when_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        run_deploy(home)
        target = home / ".agents" / "AGENTS.md"
        assert target.read_text() == SNIPPET.read_text()


def test_preserves_foreign_content_and_refreshes_managed_section() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        target = home / ".agents" / "AGENTS.md"
        target.parent.mkdir(parents=True)
        stale = "## 问题即 lint\n\n旧版本节内容\n"
        target.write_text("# AGENTS.md\n\n8 行 aliyun 运维口径,原样保留。\n\n" + stale)
        run_deploy(home)
        text = target.read_text()
        assert "8 行 aliyun 运维口径,原样保留。" in text
        assert "旧版本节内容" not in text
        assert "四条去路" in text
        expected_section = SNIPPET.read_text().split("## 问题即 lint", 1)[1]
        assert text.split("## 问题即 lint", 1)[1] == expected_section


def test_idempotent_rerun() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        run_deploy(home)
        target = home / ".agents" / "AGENTS.md"
        first = target.read_text()
        run_deploy(home)
        assert target.read_text() == first


def test_user_section_after_managed_survives() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        target = home / ".agents" / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "# AGENTS.md\n\n## 问题即 lint\n\n旧内容\n\n## my own section\n\nhand-written stuff\n\n## codemode 选取\n\n旧内容\n"
        )
        run_deploy(home)
        text = target.read_text()
        assert "## my own section" in text
        assert "hand-written stuff" in text
        assert "旧内容" not in text


def test_fenced_or_prefixed_heading_text_not_hijacked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        target = home / ".agents" / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "# AGENTS.md\n\n```\nagents-md: refreshed ## 问题即 lint\nagents-md: appended ## codemode 选取\n```\n\n### codemode 选取\n\n这是我的三级标题正文\n\n## 问题即 lint\n\n旧内容\n"
        )
        run_deploy(home)
        text = target.read_text()
        assert "agents-md: refreshed ## 问题即 lint" in text
        assert "### codemode 选取" in text
        assert "这是我的三级标题正文" in text
        assert "旧内容" not in text
        assert "四条去路" in text
        lines = text.split("\n")
        assert sum(1 for l in lines if l == "## 问题即 lint") == 1
        assert sum(1 for l in lines if l == "## codemode 选取") == 1


def test_duplicate_managed_heading_all_refreshed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        target = home / ".agents" / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text("# AGENTS.md\n\n## 问题即 lint\n\n旧一\n\n## 用户节\n\n保留我\n\n## 问题即 lint\n\n旧二\n")
        run_deploy(home)
        text = target.read_text()
        assert "旧一" not in text
        assert "旧二" not in text
        assert "保留我" in text
        assert text.count("## 问题即 lint") == 2


def test_tilde_fence_not_hijacked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        target = home / ".agents" / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "# AGENTS.md\n\n## 部署日志\n\n~~~\n## 问题即 lint\n这里是用户贴的示例正文,不该被动\n~~~\n\n尾随私有行。\n\n## 问题即 lint\n\n旧内容\n"
        )
        run_deploy(home)
        text = target.read_text()
        assert "这里是用户贴的示例正文,不该被动" in text
        assert "尾随私有行。" in text
        assert "旧内容" not in text
        assert outside_heading_count(text, "## 问题即 lint") == 1


def outside_heading_count(text: str, heading: str) -> int:
    fence = None
    count = 0
    for line in text.split("\n"):
        stripped = line.lstrip()
        if fence is None:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
                continue
        elif stripped.startswith(fence):
            fence = None
            continue
        if fence is None and line == heading:
            count += 1
    return count


def test_unterminated_fence_closed_before_append() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        target = home / ".agents" / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text("# AGENTS.md\n\n```\n未闭合围栏里的内容\n")
        run_deploy(home)
        text = target.read_text()
        assert "未闭合围栏里的内容" in text
        lines = text.split("\n")
        content_at = lines.index("未闭合围栏里的内容")
        assert "```" in lines[content_at + 1 : content_at + 3]
        run_deploy(home)
        assert target.read_text() == text


def test_library_module_not_deployed_as_extension() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        result = run_deploy(home)
        deployed = (home / ".pi" / "agent" / "extensions").glob("*.ts")
        names = {p.name for p in deployed}
        assert "compact-instructions.ts" not in names
        assert "history.ts" in names
        assert "compact-tool.ts" in names
        assert "library module" not in result
