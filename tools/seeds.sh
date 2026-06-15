#!/usr/bin/env bash
# seeds.sh — a broad idea bank, to keep explorations from collapsing into one
# theme. TWO sources, both from tetraslam's "what I want to learn" list:
#
#   1. SEEDS (default, tools/seeds.txt) — ~65 pre-framed *makeable-toy* prompts.
#      Concrete, ready to explore. Narrower (someone already picked the toy).
#   2. TOPICS (--topics, tools/topics.txt) — the full ~150 RAW topics. Feed one
#      to lain and let IT invent the toy. Broader and more surprising, since the
#      idea isn't pre-narrowed. (Includes the long tail: Hegel, maritime law,
#      organoid computing, Vocaloid, poi spinning, TigerBeetle internals, ...)
#
#   seeds.sh                       # one random seed (framed toy)
#   seeds.sh -n 5                  # 5 across distinct domains
#   seeds.sh --domain robotics     # from a specific domain
#   seeds.sh --domains             # list domains + counts
#   seeds.sh --all                 # print everything
#   seeds.sh --topics [...]        # same flags, but draw from the RAW topic list
#   seeds.sh --lain                # explore a random framed seed in lain
#   seeds.sh --topics --lain       # explore a random RAW topic (lain invents the toy)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USE_TOPICS=0
# pre-scan for --topics so we can pick the source file before the main parse
for a in "$@"; do [[ "$a" == "--topics" ]] && USE_TOPICS=1; done
if [[ "$USE_TOPICS" == "1" ]]; then
  SEEDS="$REPO_ROOT/tools/topics.txt"
else
  SEEDS="$REPO_ROOT/tools/seeds.txt"
fi
[[ -f "$SEEDS" ]] || { echo "seeds: $SEEDS not found" >&2; exit 1; }

# strip comments/blank lines
rows() { grep -vE '^\s*#|^\s*$' "$SEEDS"; }
seed_of() { printf '%s' "$1" | cut -f2-; }

n=1; domain=""; do_lain=0; mode="random"
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n) n="$2"; shift 2 ;;
    --domain) domain="$2"; shift 2 ;;
    --domains) mode="domains"; shift ;;
    --all) mode="all"; shift ;;
    --lain) do_lain=1; shift ;;
    --topics) shift ;;  # already handled (selects topics.txt as the source)
    *) echo "seeds: unknown arg '$1'" >&2; exit 2 ;;
  esac
done

case "$mode" in
  domains)
    rows | cut -f1 | sort | uniq -c | sort -rn | awk '{printf "  %-12s %s\n", $2, $1}'
    exit 0 ;;
  all)
    rows | awk -F'\t' '{printf "[%s] %s\n", $1, $2}'
    exit 0 ;;
esac

# Pick the candidate rows (optionally filtered by domain).
if [[ -n "$domain" ]]; then
  pool="$(rows | awk -F'\t' -v d="$domain" '$1==d')"
  [[ -n "$pool" ]] || { echo "seeds: no seeds for domain '$domain' (try --domains)" >&2; exit 1; }
else
  pool="$(rows)"
fi

# Random selection. For n>1 without a domain filter, prefer distinct domains.
pick() {
  local count="$1"
  if [[ -z "$domain" && "$count" -gt 1 ]]; then
    # one per distinct domain first, then fill
    { printf '%s\n' "$pool" | awk -F'\t' '!seen[$1]++'; printf '%s\n' "$pool"; } \
      | awk 'NF' | shuf | head -n "$count"
  else
    printf '%s\n' "$pool" | shuf | head -n "$count"
  fi
}

selected="$(pick "$n")"

if [[ "$do_lain" == "1" ]]; then
  command -v lain >/dev/null 2>&1 || { echo "seeds: 'lain' not installed" >&2; exit 1; }
  raw="$(seed_of "$(printf '%s\n' "$selected" | head -1)")"
  if [[ "$USE_TOPICS" == "1" ]]; then
    # raw topic -> let lain make the creative leap to a toy
    seed="a small, makeable, visual/interactive playground toy that teaches or explores: ${raw}. Invent the toy itself; it should run locally and produce something you can look at or interact with."
    label="$raw"
  else
    seed="$raw"
    label="$raw"
  fi
  db="$HOME/$(printf '%s' "$label" | tr ' ' '-' | tr -cd 'a-zA-Z0-9-' | cut -c1-40).db"
  echo "seeds: exploring -> \"$label\""
  echo "       (db: $db)"
  # Use the explicit `explore` subcommand (the documented escape hatch) rather
  # than the inferred `lain "<seed>"` form: as of lain's bareword guard
  # (commit 3423d3f), a single-word seed that looks like a command would error
  # instead of exploring. `explore` always treats the argument as a seed.
  exec lain explore "$seed" -n 3 -m 1 --db "$db"
fi

# default: just print the seed(s)
printf '%s\n' "$selected" | awk -F'\t' '{printf "[%s] %s\n", $1, $2}'
