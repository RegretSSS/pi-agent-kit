#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $# -ne 1 ]]; then
	echo "usage: enable-gate.sh <repo>" >&2
	exit 2
fi

repo="$(cd "$1" && pwd)"

if [[ ! -d "${repo}/.git" ]]; then
	echo "enable-gate: ${repo} 不是 git 仓库" >&2
	exit 1
fi

pre_commit="${repo}/.git/hooks/pre-commit"
commit_msg="${repo}/.git/hooks/commit-msg"

pre_commit_body="#!/usr/bin/env bash
LINT_ROOT=\"\$(cd \"\$(dirname \"\${BASH_SOURCE[0]}\")/../..\" && pwd)\" \"${KIT_ROOT}/scripts/run-lints.sh\"
"

commit_msg_body="#!/usr/bin/env bash
\"${KIT_ROOT}/scripts/commit-msg-hook\" \"\$1\"
"

install_hook() {
	local target="$1" body="$2"
	if [[ -f "${target}" ]] && ! grep -q "run-lints.sh\|commit-msg-hook" "${target}"; then
		echo "enable-gate: ${target} 已存在且非本仓安装,拒绝覆盖" >&2
		exit 1
	fi
	printf '%s' "${body}" > "${target}"
	chmod +x "${target}"
	echo "enable-gate: installed $(basename "${target}") hook -> ${target}"
}

install_hook "${pre_commit}" "${pre_commit_body}"
install_hook "${commit_msg}" "${commit_msg_body}"
