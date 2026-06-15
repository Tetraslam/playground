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

# Insert the entry under the section header (replacing the "_(none yet)_"
# placeholder if present). Logic lives in _feedback_insert.py — run via uv.
uv run --no-project --quiet "$REPO_ROOT/tools/_feedback_insert.py" "$FILE" "$header" "$entry"

echo "✓ logged [$cat] to FEEDBACK.md: $msg"
echo "  (commit it so it persists: git add FEEDBACK.md && git commit)"
