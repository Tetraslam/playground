#!/usr/bin/env bash
# feedback.sh — append a structured entry to FEEDBACK.md.
#
#   tools/feedback.sh <category> "<message>"
#
# Categories: access | setup | note | idea | onboard
#   access   — "I need a tool/key/permission" (needs a human decision)
#   setup    — "a config/file should change" (should become a PR)
#   note     — durable fact future agents need
#   idea     — a toy worth building
#   onboard  — AGENTS.md/README didn't answer something
#
# Entries are timestamped and attributed. Author defaults to $FEEDBACK_AUTHOR,
# else "agent". Set FEEDBACK_AUTHOR=claude (or your name) to attribute properly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$REPO_ROOT/FEEDBACK.md"

usage() {
  echo "usage: tools/feedback.sh <access|setup|note|idea|onboard> \"<message>\"" >&2
  exit 2
}

[[ $# -ge 2 ]] || usage
cat="$1"; shift
msg="$*"
author="${FEEDBACK_AUTHOR:-agent}"
date="$(date +%Y-%m-%d)"

# Map category -> the section header it lives under.
case "$cat" in
  access)  header="## access — capability requests (need a human decision)" ;;
  setup)   header="## setup — config/environment changes (should become a PR)" ;;
  note)    header="## note — durable knowledge for future agents" ;;
  idea)    header="## idea — toys worth building" ;;
  onboard) header="## onboard — docs that should've answered something" ;;
  *) echo "feedback: unknown category '$cat'" >&2; usage ;;
esac

[[ -f "$FILE" ]] || { echo "feedback: $FILE not found" >&2; exit 1; }

entry="- ${date} · ${author} · ${msg}"

# Insert the entry directly after the section header. If the section currently
# holds the "_(none yet)_" placeholder, replace it instead of stacking under it.
python3 - "$FILE" "$header" "$entry" <<'PY'
import sys, io

path, header, entry = sys.argv[1], sys.argv[2], sys.argv[3]
with io.open(path, encoding="utf-8") as f:
    lines = f.read().split("\n")

out, inserted = [], False
i = 0
while i < len(lines):
    out.append(lines[i])
    if not inserted and lines[i].strip() == header.strip():
        # advance past blank lines right under the header
        j = i + 1
        # collect the block until the next "## " header or EOF
        # if the first non-blank line is the placeholder, drop it
        # find first content line
        k = j
        while k < len(lines) and lines[k].strip() == "":
            k += 1
        if k < len(lines) and lines[k].strip() == "_(none yet)_":
            # replace placeholder: emit a blank line + entry, skip placeholder
            out.append("")
            out.append(entry)
            i = k  # skip up to and including placeholder
            inserted = True
            i += 1
            continue
        else:
            # prepend entry as the newest item under the header
            out.append("")
            out.append(entry)
            inserted = True
    i += 1

if not inserted:
    sys.stderr.write("feedback: section header not found, nothing appended\n")
    sys.exit(1)

with io.open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
PY

echo "✓ logged [$cat] to FEEDBACK.md: $msg"
echo "  (commit it so it persists: git add FEEDBACK.md && git commit)"
