#!/usr/bin/env bash
set -euo pipefail

CC_CONFIG="${HOME}/.claude.json"
PI_MCP="${HOME}/.pi/agent/mcp.json"
SYNC_SERVERS=("zai-mcp-server" "web-search-prime" "web-reader")

if [[ ! -f "${CC_CONFIG}" ]]; then
	echo "sync-mcp: ${CC_CONFIG} 不存在" >&2
	exit 1
fi

python3 - "${CC_CONFIG}" "${PI_MCP}" "${SYNC_SERVERS[@]}" <<'PY'
import json
import pathlib
import sys

cc_path, pi_path = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
wanted = sys.argv[3:]
sources = json.loads(cc_path.read_text()).get("mcpServers", {})
missing = [name for name in wanted if name not in sources]
if missing:
    print(f"sync-mcp: CC 配置缺 server: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)

pi = {"mcpServers": {}}
if pi_path.exists():
    pi = json.loads(pi_path.read_text())
servers = pi.setdefault("mcpServers", {})
for name in wanted:
    servers[name] = sources[name]
pi_path.parent.mkdir(parents=True, exist_ok=True)
pi_path.write_text(json.dumps(pi, ensure_ascii=False, indent=1) + "\n")
pi_path.chmod(0o600)

for name in wanted:
    print(f"sync-mcp: synced {name}")
kept = sorted(name for name in servers if name not in wanted)
print(f"sync-mcp: kept {', '.join(kept) if kept else '(none)'}")
PY
