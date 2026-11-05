#!/usr/bin/env bash
set -euo pipefail

dest="${PI_AGENT_KIT_DIR:-$HOME/.pi-agent-kit}"

if [[ ! -d "${dest}/.git" ]]; then
	git clone --depth 1 https://github.com/RegretSSS/pi-agent-kit "${dest}"
else
	git -C "${dest}" pull --ff-only >/dev/null
fi

"${dest}/deploy.sh"

echo
echo "pi-agent-kit: installed at ${dest}"
echo "重启 pi 后生效;可选: ${dest}/scripts/enable-gate.sh <你的项目仓>"
