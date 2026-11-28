import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "sync-subagents-kit.mjs"


def make_kit(root: Path, version: str = "0.23.2") -> Path:
    kit = root / "kit"
    (kit / "src" / "workflow").mkdir(parents=True)
    (kit / "package.json").write_text(json.dumps({"name": "@tintinweb/pi-subagents", "version": version}), encoding="utf-8")
    (kit / "src" / "index.ts").write_text("export const fromKit = 1;\n", encoding="utf-8")
    (kit / "src" / "workflow" / "task.ts").write_text("export const task = 1;\n", encoding="utf-8")
    git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(kit)]
    subprocess.run([*git, "init", "-q", "-b", "kit"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "kit"], check=True)
    return kit


def make_package(root: Path, version: str = "0.23.2", stale: bool = True) -> Path:
    package = root / "node_modules" / "@tintinweb" / "pi-subagents"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    if stale:
        (package / "src").mkdir()
        (package / "src" / "index.ts").write_text("stale\n", encoding="utf-8")
        (package / "src" / "orphan.ts").write_text("leftover\n", encoding="utf-8")
    return package


def run(package: Path, kit: Path, tmp: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PI_SUBAGENTS_PKG=str(package), PI_SUBAGENTS_KIT=str(kit), TMPDIR=str(tmp))
    return subprocess.run(["node", str(SCRIPT)], capture_output=True, text=True, env=env, cwd=REPO)


def test_sync_replaces_src_with_kit_branch_and_is_idempotent(tmp_path) -> None:
    kit = make_kit(tmp_path)
    package = make_package(tmp_path)
    tmp = tmp_path / "tmp"
    (tmp / "jiti").mkdir(parents=True)
    first = run(package, kit, tmp)
    assert first.returncode == 0, first.stderr
    assert "已把 kit" in first.stdout and "清理 jiti" in first.stdout
    assert (package / "src" / "index.ts").read_text(encoding="utf-8") == "export const fromKit = 1;\n"
    assert (package / "src" / "workflow" / "task.ts").exists()
    assert not (package / "src" / "orphan.ts").exists()
    assert not (package / "src.replaced").exists()
    assert not (tmp / "jiti").exists()
    second = run(package, kit, tmp)
    assert second.returncode == 0, second.stderr
    assert "跳过" in second.stdout


def test_sync_refuses_on_version_mismatch_without_touching(tmp_path) -> None:
    kit = make_kit(tmp_path, version="0.26.3")
    package = make_package(tmp_path, version="0.23.2")
    result = run(package, kit, tmp_path / "tmp")
    assert result.returncode == 1
    assert "基线是 0.26.3" in result.stderr and "已安装的是 0.23.2" in result.stderr
    assert (package / "src" / "index.ts").read_text(encoding="utf-8") == "stale\n"
    assert not (package / "src.replaced").exists()


def test_sync_skips_when_package_missing(tmp_path) -> None:
    kit = make_kit(tmp_path)
    result = run(tmp_path / "nowhere", kit, tmp_path / "tmp")
    assert result.returncode == 0, result.stderr
    assert "跳过" in result.stdout


def test_sync_reports_missing_kit_repo(tmp_path) -> None:
    package = make_package(tmp_path)
    result = run(package, tmp_path / "no-kit", tmp_path / "tmp")
    assert result.returncode == 1
    assert "sync-subagents-kit: 失败" in result.stderr
    assert (package / "src" / "index.ts").read_text(encoding="utf-8") == "stale\n"
