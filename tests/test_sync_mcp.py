import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "sync-mcp.sh"

CC_MCP = {
    "mcpServers": {
        "zai-mcp-server": {"type": "stdio", "command": "npx", "args": ["-y", "zai"]},
        "web-search-prime": {"type": "http", "url": "https://x/s/mcp", "headers": {"Authorization": "Bearer t"}},
        "web-reader": {"type": "http", "url": "https://x/r/mcp", "headers": {"Authorization": "Bearer t"}},
        "unrelated": {"command": "x", "args": []},
    }
}


def run(home: Path) -> str:
    return subprocess.run(
        [str(SCRIPT)],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def setup(home: Path, existing_pi: dict | None) -> Path:
    (home / ".claude.json").write_text(json.dumps(CC_MCP))
    pi_mcp = home / ".pi" / "agent" / "mcp.json"
    if existing_pi is not None:
        pi_mcp.parent.mkdir(parents=True)
        pi_mcp.write_text(json.dumps(existing_pi))
    return pi_mcp


def test_merges_into_empty_and_keeps_mailbox(tmp_path) -> None:
    pi_mcp = setup(tmp_path, {"mcpServers": {"mailbox": {"command": "/usr/bin/python3", "args": ["/m.py"]}}})
    out = run(tmp_path)
    merged = json.loads(pi_mcp.read_text())["mcpServers"]
    assert set(merged) == {"mailbox", "zai-mcp-server", "web-search-prime", "web-reader"}
    assert merged["web-search-prime"]["url"] == "https://x/s/mcp"
    assert merged["mailbox"]["args"] == ["/m.py"]
    assert "unrelated" not in merged
    assert "kept mailbox" in out


def test_idempotent_rerun(tmp_path) -> None:
    pi_mcp = setup(tmp_path, None)
    run(tmp_path)
    first = pi_mcp.read_text()
    run(tmp_path)
    assert pi_mcp.read_text() == first


def test_fails_when_source_missing(tmp_path) -> None:
    setup(tmp_path, None)
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {}}))
    result = subprocess.run(
        [str(SCRIPT)],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "缺 server" in result.stderr
