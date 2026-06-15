#!/usr/bin/env bash
# lain-toy.sh — scaffold a playground toy from a lain exploration.
#
# Closes the loop: lain (tetraslam's ideation engine) generates ideas; this
# turns a chosen idea node into a real toy directory. lain stays 100%
# self-contained — we only call its PUBLIC CLI (`lain export`) and read the
# markdown it emits. No coupling to lain's db schema or internals.
#
# USAGE
#   # 1. list the idea nodes in a lain .db:
#   tools/lain-toy.sh list <exploration.db>
#
#   # 2. scaffold a toy from one node (creates toys/<slug>/):
#   tools/lain-toy.sh scaffold <exploration.db> <node-id> [--lang py|go|ts|rust]
#
# Requires: lain (installed), uv (for the markdown parser). The .db path is
# whatever lain wrote — e.g. ~/my-exploration.db.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARSE="uv run --no-project --quiet $REPO_ROOT/tools/_lain_toy.py"

usage() {
  echo "usage:" >&2
  echo "  tools/lain-toy.sh list <db>" >&2
  echo "  tools/lain-toy.sh scaffold <db> <node-id> [--lang py|go|ts|rust]" >&2
  exit 2
}

command -v lain >/dev/null 2>&1 || { echo "lain-toy: 'lain' not installed (curl -fsSL https://tetraslam.github.io/lain/install | bash)" >&2; exit 1; }

cmd="${1:-}"; shift || usage
[[ -n "${1:-}" ]] || usage
DB="$1"; shift || true
[[ -f "$DB" ]] || { echo "lain-toy: db not found: $DB" >&2; exit 1; }

# Export the exploration to a temp dir (lain's public command, black-box).
EXPORT_DIR="$(mktemp -d)"
trap 'rm -rf "$EXPORT_DIR"' EXIT
lain export "$DB" --out "$EXPORT_DIR" >/dev/null 2>&1 \
  || { echo "lain-toy: 'lain export' failed for $DB" >&2; exit 1; }

case "$cmd" in
  list)
    echo "idea nodes in $(basename "$DB"):"
    $PARSE list "$EXPORT_DIR" | while IFS=$'\t' read -r id title; do
      printf "  %-10s %s\n" "$id" "$title"
    done
    ;;
  scaffold)
    node="${1:-}"; shift || true
    [[ -n "$node" ]] || { echo "lain-toy: scaffold needs a <node-id> (see 'list')" >&2; exit 2; }
    lang="py"
    while [[ $# -gt 0 ]]; do
      case "$1" in --lang) lang="$2"; shift 2;; *) echo "lain-toy: unknown arg $1" >&2; exit 2;; esac
    done

    slug="$($PARSE slug "$EXPORT_DIR" "$node")"
    dir="$REPO_ROOT/toys/$slug"
    [[ -e "$dir" ]] && { echo "lain-toy: toys/$slug already exists" >&2; exit 1; }
    mkdir -p "$dir"

    # README carries the full idea forward as a design doc.
    $PARSE readme "$EXPORT_DIR" "$node" > "$dir/README.md"

    # language-appropriate stub + workspace wiring
    case "$lang" in
      py)
        cat > "$dir/pyproject.toml" <<EOF
[project]
name = "$slug"
version = "0.1.0"
description = "Scaffolded from a lain exploration ($node)."
requires-python = ">=3.12"
dependencies = []
EOF
        cat > "$dir/main.py" <<EOF
"""$slug — scaffolded from a lain exploration ($node). See README.md for the idea.

    uv run python toys/$slug/main.py
"""


def main() -> None:
    print("TODO: implement '$slug' — see README.md for the design.")


if __name__ == "__main__":
    main()
EOF
        echo "note: add '\"toys/$slug\"' to [tool.uv.workspace].members in the root pyproject.toml, then 'uv sync'." ;;
      go)
        ( cd "$dir" && go mod init "playground/$slug" >/dev/null 2>&1 )
        cat > "$dir/main.go" <<EOF
// $slug — scaffolded from a lain exploration ($node). See README.md.
package main

import "fmt"

func main() {
	fmt.Println("TODO: implement '$slug' — see README.md for the design.")
}
EOF
        echo "note: add 'use ./toys/$slug' to go.work." ;;
      ts)
        cat > "$dir/package.json" <<EOF
{
  "name": "$slug",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": { "start": "node index.ts" }
}
EOF
        cat > "$dir/index.ts" <<EOF
// $slug — scaffolded from a lain exploration ($node). See README.md.
console.log("TODO: implement '$slug' — see README.md for the design.");
EOF
        echo "note: run 'pnpm install' to pick up toys/$slug." ;;
      rust)
        ( cd "$REPO_ROOT" && cargo new --quiet "toys/$slug" 2>/dev/null ) || true
        echo "note: cargo workspace picks up toys/$slug via the toys/* glob." ;;
      *) echo "lain-toy: unknown --lang '$lang' (py|go|ts|rust)" >&2; rm -rf "$dir"; exit 2 ;;
    esac

    echo "✓ scaffolded toys/$slug/ ($lang) from lain node $node"
    echo "  README.md carries the full idea. Go build it."
    ;;
  *) usage ;;
esac
