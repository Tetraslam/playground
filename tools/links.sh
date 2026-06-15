#!/usr/bin/env bash
# links.sh — browse + contribute to the link collection.
#
# TWO SOURCES, merged for reading:
#   1. UPSTREAM (read-only): tetraslam's personal curated collection at
#      https://tetraslam.world/links.md — his taste, agents never write to it.
#   2. LOCAL (read+write):   RESOURCES.md in this repo — where AGENTS add links.
#
# Reads merge both; writes only ever touch the local RESOURCES.md.
#
#   tools/links.sh                       # list all entries (both sources)
#   tools/links.sh ml                    # entries tagged "ml"
#   tools/links.sh ml rl                 # tagged "ml" AND "rl"
#   tools/links.sh --tags                # tag cloud with counts
#   tools/links.sh --local               # only the agent-contributed pile
#   tools/links.sh --add <tags> <url> <why>   # add a link to RESOURCES.md
#
# tags for --add are comma-separated, e.g.  ml,rl,paper
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_FILE="$REPO_ROOT/RESOURCES.md"
UPSTREAM_URL="${LINKS_URL:-https://tetraslam.world/links.md}"

# ---- add mode -------------------------------------------------------------
if [[ "${1:-}" == "--add" ]]; then
  shift
  [[ $# -ge 3 ]] || { echo "usage: tools/links.sh --add <tags> <url> \"<why>\"" >&2; exit 2; }
  tags="$1"; url="$2"; shift 2; why="$*"
  [[ "$url" =~ ^https?:// ]] || { echo "links: url must start with http(s):// (got '$url')" >&2; exit 2; }
  if grep -qF "$url" "$LOCAL_FILE" 2>/dev/null; then
    echo "links: $url already in RESOURCES.md, skipping" >&2; exit 0
  fi
  # normalize tags: lowercase, comma+space separated
  norm_tags="$(printf '%s' "$tags" | tr 'A-Z' 'a-z' | tr ',' '\n' | sed '/^$/d' | paste -sd', ')"
  title="${LINKS_TITLE:-$why}"
  {
    printf '\n### %s\n\n' "$title"
    printf -- '- **Tags**: %s\n' "$norm_tags"
    printf -- '- **URL**: %s\n\n---\n' "$url"
  } >> "$LOCAL_FILE"
  echo "✓ added to RESOURCES.md: $title  [$norm_tags]"
  echo "  commit it: git add RESOURCES.md && git commit"
  exit 0
fi

# ---- read modes -----------------------------------------------------------
# Gather both sources into a temp file (avoids pipefail/SIGPIPE races between
# curl and the downstream python parser), then echo the file path.
gather() {
  local tmp; tmp="$(mktemp)"
  curl -fsSL "$UPSTREAM_URL" >>"$tmp" 2>/dev/null || true
  printf '\n' >>"$tmp"
  cat "$LOCAL_FILE" >>"$tmp" 2>/dev/null || true
  printf '%s' "$tmp"
}

FEED="$(gather)"
trap 'rm -f "$FEED"' EXIT

case "${1:-}" in
  --raw)   cat "$FEED"; exit 0 ;;
  --local) cat "$LOCAL_FILE"; exit 0 ;;
  --tags)
    uv run --no-project --quiet "$REPO_ROOT/tools/_links_parse.py" --tags "$FEED"
    exit 0 ;;
esac

# Default / tag-filter: remaining args are tags to AND-match (empty = all).
uv run --no-project --quiet "$REPO_ROOT/tools/_links_parse.py" --filter "$FEED" "$@"
