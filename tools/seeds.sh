#!/usr/bin/env bash
# seeds.sh — a broad idea seed bank, to keep explorations from collapsing into
# one theme. Seeds are drawn from tetraslam's "what I want to learn" list and
# framed as *makeable toys*, spanning ~18 domains (finance, ai, bio, cs-math,
# robotics, security, energy, graphics, ...). Source: tools/seeds.txt.
#
#   seeds.sh                      # one random seed
#   seeds.sh -n 5                 # 5 random seeds (distinct domains when possible)
#   seeds.sh --domain robotics    # one random seed from a domain
#   seeds.sh --domains            # list available domains + counts
#   seeds.sh --all                # print every seed
#   seeds.sh --lain [-n N]        # run a lain exploration on a random seed
#
# The --lain mode pipes a seed straight into your ideation engine:
#   seeds.sh --lain               # explore one random broad seed
#   seeds.sh --domain bio --lain  # explore a random bio seed
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEEDS="$REPO_ROOT/tools/seeds.txt"
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
  # explore the first selected seed
  seed="$(seed_of "$(printf '%s\n' "$selected" | head -1)")"
  db="$HOME/$(printf '%s' "$seed" | tr ' ' '-' | tr -cd 'a-zA-Z0-9-' | cut -c1-40).db"
  echo "seeds: exploring -> \"$seed\""
  echo "       (db: $db)"
  exec lain "$seed" -n 3 -m 1 --db "$db"
fi

# default: just print the seed(s)
printf '%s\n' "$selected" | awk -F'\t' '{printf "[%s] %s\n", $1, $2}'
