#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "$0")" && pwd)"

if [[ $# -ne 1 ]]; then
	echo "usage: enable-gate.sh <repo>" >&2
	exit 2
fi

repo="$(cd "$1" && pwd)"
hook="${repo}/.git/hooks/pre-commit"

if [[ ! -d "${repo}/.git" ]]; then
	echo "enable-gate: ${repo} 不是 git 仓库" >&2
	exit 1
fi

hook_body="#!/usr/bin/env bash
\"${KIT_ROOT}/run-lints.sh\"
"

if [[ -f "${hook}" ]] && ! grep -q "run-lints.sh" "${hook}"; then
	echo "enable-gate: ${hook} 已存在且非本仓安装,拒绝覆盖" >&2
	exit 1
fi

printf '%s' "${hook_body}" > "${hook}"
chmod +x "${hook}"
echo "enable-gate: installed pre-commit hook -> ${hook}"
