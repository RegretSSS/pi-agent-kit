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


def fence_marks(lines):
    open_fence = None
    for line in lines:
        stripped = line.lstrip()
        if open_fence is None:
            if stripped.startswith("```"):
                open_fence = "```"
            elif stripped.startswith("~~~"):
                open_fence = "~~~"
            continue
        if stripped.startswith(open_fence):
            open_fence = None
    return open_fence


def heading2_indexes(lines):
    fence = None
    starts = []
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if fence is None:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
                continue
        elif stripped.startswith(fence):
            fence = None
            continue
        if fence is not None:
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
        unterminated = fence_marks(lines)
        if unterminated:
            lines.append(unterminated)
            print("agents-md: closed unterminated fence before appending")
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
	local exclude=("compact-instructions.ts")
	mkdir -p "${dest}"
	for src in extensions/*.ts; do
		local base
		base="$(basename "${src}")"
		if [[ " ${exclude[*]} " == *" ${base} "* ]]; then
			continue
		fi
		cp "${src}" "${dest}/${base}"
		echo "extensions: deployed ${base}"
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
