#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export LINT_ROOT="${LINT_ROOT:-$(pwd)}"
export COMMIT_MUST_CLEAR_REPO="${COMMIT_MUST_CLEAR_REPO:-${LINT_ROOT}}"
status=0
for rule in lints/*.py; do
	name="$(basename "${rule}" .py)"
	echo "== ${name}"
	python3 "${rule}" || status=1
done
exit "${status}"
