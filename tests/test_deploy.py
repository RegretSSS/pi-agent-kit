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
