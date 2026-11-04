import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "lints" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def make_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-q", "-m", "init")
    return repo


class TestCommitMustClearGitStatus:
    def test_clean_and_staged_only_pass(self, tmp_path) -> None:
        mod = load("commit_must_clear_git_status")
        repo = make_repo(tmp_path)
        assert mod.lint(repo) == []
        (repo / "f.txt").write_text("y")
        git(repo, "add", "f.txt")
        assert mod.lint(repo) == []

    def test_unstaged_and_untracked_fail(self, tmp_path) -> None:
        mod = load("commit_must_clear_git_status")
        repo = make_repo(tmp_path)
        (repo / "f.txt").write_text("y")
        assert "工作树未收干净" in mod.lint(repo)[0]
        (repo / "f.txt").write_text("x")
        (repo / "new.txt").write_text("z")
        assert "工作树未收干净" in mod.lint(repo)[0]


class TestNoSecrets:
    def test_clean_tree_passes(self, tmp_path) -> None:
        mod = load("no_secrets")
        assert mod.lint(REPO) == []

    def test_detects_each_shape(self, tmp_path) -> None:
        mod = load("no_secrets")
        samples = {
            "a.md": "key=" + "sk-" + "abcdefghij01234567",
            "b.md": "tok=" + "ghp_" + "a" * 32,
            "c.md": "tok=" + "github_pat_" + "A" * 22,
            "d.md": "aws=" + "AKIA" + "IOSFODNN7EXAMPLE",
            "e.md": "slack=" + "xoxb-" + "1" * 24,
            "f.md": "v=" + "zai-" + "server-abcdefgh1234",
            "g.md": "k=" + "bd8aa8d296114e6391019b41da22d119" + "." + "Wjsb9i14oI7DxQ",
        }
        for name, text in samples.items():
            (tmp_path / name).write_text(text)
        problems = mod.lint(tmp_path)
        assert len(problems) == len(samples)

    def test_lint_definition_file_exempt(self, tmp_path) -> None:
        mod = load("no_secrets")
        exempt = tmp_path / "lints"
        exempt.mkdir()
        (exempt / "no_secrets.py").write_text("key=" + "sk-" + "abcdefghij01234567")
        assert mod.lint(tmp_path) == []


class TestZeroComments:
    def test_repo_sources_pass(self) -> None:
        mod = load("zero_comments")
        assert mod.lint(REPO) == []

    def test_flags_each_language(self, tmp_path) -> None:
        mod = load("zero_comments")
        (tmp_path / "a.py").write_text("x = 1\n# note\n")
        (tmp_path / "b.sh").write_text("#!/usr/bin/env bash\n# note\ntrue\n")
        (tmp_path / "c.ts").write_text("const u = 'https://x.dev/a';\n// note\n")
        (tmp_path / "d.ts").write_text("const y = 1;\n/* block */\n")
        found = mod.lint(tmp_path)
        assert len(found) == 4

    def test_shebang_and_url_pass(self, tmp_path) -> None:
        mod = load("zero_comments")
        (tmp_path / "a.sh").write_text("#!/usr/bin/env bash\ntrue\n")
        (tmp_path / "b.ts").write_text("const u = 'https://x.dev/a';\n")
        assert mod.lint(tmp_path) == []


class TestAgentsmdIndexConsistency:
    def test_absent_dir_passes(self, tmp_path) -> None:
        mod = load("agentsmd_index_consistency")
        assert mod.lint(tmp_path / "nope") == []

    def test_consistent_dir_passes(self, tmp_path) -> None:
        mod = load("agentsmd_index_consistency")
        (tmp_path / "aliyun.md").write_text("---\nname: aliyun\n---\nbody")
        (tmp_path / "MEMORY.md").write_text("- [aliyun](aliyun.md) — hook\n")
        assert mod.lint(tmp_path) == []

    def test_both_directions_flagged(self, tmp_path) -> None:
        mod = load("agentsmd_index_consistency")
        (tmp_path / "orphan.md").write_text("body")
        (tmp_path / "MEMORY.md").write_text("- [ghost](ghost.md) — hook\n")
        problems = "\n".join(mod.lint(tmp_path))
        assert "缺索引行 orphan.md" in problems
        assert "指向不存在的文件 ghost.md" in problems


def test_run_lints_green(tmp_path) -> None:
    clean_repo = make_repo(tmp_path)
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(tmp_path / "home"),
        "COMMIT_MUST_CLEAR_REPO": str(clean_repo),
        "AGENTS_MEMORY_DIR": str(tmp_path / "no-memory"),
    }
    result = subprocess.run(
        [str(REPO / "scripts" / "run-lints.sh")],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
