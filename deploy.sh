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


def heading2_indexes(lines):
    fence = False
    starts = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if line.startswith("## "):
            starts.append(i)
    return starts


def section_lines(text, heading):
    lines = text.split("\n")
    starts = heading2_indexes(lines)
    for i in starts:
        if lines[i] == heading:
            end = next((j for j in starts if j > i), len(lines))
            body = lines[i:end]
            while body and body[-1].strip() == "":
                body.pop()
            return body
    return None


managed = {h: section_lines(snippet, h) for h in headings}
lines = target.read_text().split("\n")
starts = heading2_indexes(lines)
changed = []
for heading in headings:
    body = managed[heading]
    if body is None:
        continue
    occurrences = [i for i in starts if lines[i] == heading]
    if not occurrences:
        while lines and lines[-1].strip() == "":
            lines.pop()
        lines += ["", *body, ""]
        changed.append(f"appended {heading}")
        continue
    for i in reversed(occurrences):
        end = next((j for j in starts if j > i), len(lines))
        replacement = list(body)
        if end < len(lines):
            replacement.append("")
        lines[i:end] = replacement
        starts = heading2_indexes(lines)
    changed.append(f"refreshed {heading}" + (" (x%d)" % len(occurrences) if len(occurrences) > 1 else ""))
while lines and lines[-1] == "":
    lines.pop()
if lines:
    lines.append("")
target.write_text("\n".join(lines))
for entry in changed:
    print(f"agents-md: {entry}")
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
