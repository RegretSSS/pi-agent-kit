#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
status=0
for rule in lints/*.py; do
	name="$(basename "${rule}" .py)"
	echo "== ${name}"
	python3 "${rule}" || status=1
done
exit "${status}"
