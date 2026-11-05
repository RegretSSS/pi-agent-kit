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
headings = ["## 问题即 lint", "## codemode 选取"]


def sections_of(text):
    found = {}
    for heading in headings:
        start = text.find(heading)
        if start == -1:
            continue
        ends = [text.find(h, start + len(heading)) for h in headings if h != heading]
        ends = [e for e in ends if e != -1]
        found[heading] = text[start : min(ends) if ends else len(text)].rstrip("\n")
    return found


managed = sections_of(snippet)
text = target.read_text()
existing = sections_of(text)
out = text
for heading in headings:
    if heading not in managed:
        continue
    if heading in existing:
        start = out.find(heading)
        ends = [out.find(h, start + len(heading)) for h in headings if h != heading]
        ends = [e for e in ends if e != -1]
        end = min(ends) if ends else len(out)
        out = out[:start].rstrip("\n") + "\n\n" + managed[heading] + "\n" + (out[end:].lstrip("\n") if end < len(out) else "")
        print(f"agents-md: refreshed {heading}")
    else:
        out = out.rstrip("\n") + "\n\n" + managed[heading] + "\n"
        print(f"agents-md: appended {heading}")
target.write_text(out)
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
