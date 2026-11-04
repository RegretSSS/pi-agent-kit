#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

install_agents_md() {
	local target="${HOME}/.agents/AGENTS.md"
	mkdir -p "$(dirname "${target}")"
	if [[ ! -f "${target}" ]]; then
		cp agents-md/snippet.md "${target}"
		echo "agents-md: created ${target}"
		return
	fi
	python3 - "${target}" <<'PY'
import pathlib
import sys

target = pathlib.Path(sys.argv[1])
snippet = pathlib.Path("agents-md/snippet.md").read_text()
heading = "## 问题即 lint"
section = snippet[snippet.index(heading) :]
text = target.read_text()
if heading in text:
    head = text[: text.index(heading)].rstrip("\n")
    target.write_text((head + "\n\n" if head else "") + section)
    print("agents-md: refreshed managed section")
else:
    target.write_text(text.rstrip("\n") + "\n\n" + section)
    print("agents-md: appended managed section")
PY
}

install_extensions() {
	local dest="${HOME}/.pi/agent/extensions"
	mkdir -p "${dest}"
	for src in extensions/*.ts; do
		cp "${src}" "${dest}/$(basename "${src}")"
		echo "extensions: deployed $(basename "${src}")"
	done
}

install_skills() {
	for dir in skills/*/; do
		local name
		name="$(basename "${dir}")"
		if [[ -f "${dir}SKILL.md" ]]; then
			mkdir -p "${HOME}/.agents/skills/${name}"
			cp "${dir}SKILL.md" "${HOME}/.agents/skills/${name}/SKILL.md"
			echo "skills: deployed ${name}"
		fi
	done
}

main() {
	install_agents_md
	install_extensions
	install_skills
	if [[ -f "${HOME}/.claude.json" ]]; then
		"./scripts/sync-mcp.sh"
	fi
}

main "$@"
