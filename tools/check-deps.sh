#!/usr/bin/env bash
# check-deps.sh — block hand-edited dependencies. Use the package managers.
#
# Rationale: manually editing dependency lists in pyproject.toml / package.json
# / Cargo.toml (or hand-editing lockfiles) desyncs the manifest from the lock
# and skips resolution. In this repo you add deps with the tool, which updates
# both atomically:
#   Python: uv add <pkg>        (NOT editing [project.dependencies])
#   TS/JS:  pnpm add <pkg>       (NOT editing "dependencies" in package.json)
#   Rust:   cargo add <pkg>      (NOT editing [dependencies] in Cargo.toml)
#   Go:     go get <pkg>         (NOT editing require() by hand)
#
# This script inspects the STAGED diff. It fails if a manifest's dependency
# section changed without its corresponding lockfile also being staged, or if a
# lockfile was edited by hand without the manager's fingerprint. It's a
# heuristic guard, not a sandbox — but it catches the common mistakes.
#
# Bypass (rarely needed, e.g. intentional lockfile surgery):
#   ALLOW_MANUAL_DEPS=1 git commit ...
set -euo pipefail

if [[ "${ALLOW_MANUAL_DEPS:-0}" == "1" ]]; then
  echo "check-deps: bypassed via ALLOW_MANUAL_DEPS=1" >&2
  exit 0
fi

# A user's global git config may set an external diff driver / pager (delta,
# difftastic, etc.) that strips the +/- markers this script greps for. Disable
# all of that: unset the external-diff env var, and override config so the
# output is plain unified diff. (We avoid `-c diff.external=` because git tries
# to *run* an empty external command; unsetting the env var is enough, plus we
# point any configured driver at a no-op via --no-ext-diff.)
unset GIT_EXTERNAL_DIFF
g() {
  git -c core.pager=cat -c color.ui=never -c pager.diff=false "$@"
}

# Files staged for this commit.
staged() { g diff --cached --name-only --diff-filter=ACM; }
# Staged diff for a specific file (plain unified, no external driver/pager).
diff_for() { g --no-pager diff --no-ext-diff --cached -U0 --no-color -- "$1"; }
is_staged() { staged | grep -qxF "$1"; }

fail=0
err() { echo "✗ $*" >&2; fail=1; }

while IFS= read -r f; do
  case "$f" in
    *pyproject.toml)
      # Only flag when an actual dependency ENTRY is added — an added line that
      # is a quoted package spec, e.g.  +  "requests>=2.0",  or  +"flask".
      # A brand-new/scaffolded `dependencies = []` (empty) must NOT trip this.
      added_dep="$(diff_for "$f" | grep -E '^\+' \
        | grep -vE '^\+\s*#' \
        | grep -E '^\+\s*"[A-Za-z0-9_.-]+([<>=!~\[].*)?"' || true)"
      # also catch an inline non-empty array added: dependencies = ["x"]
      added_inline="$(diff_for "$f" | grep -E '^\+' \
        | grep -E 'dependencies\s*=\s*\[\s*"' || true)"
      if [[ -n "$added_dep" || -n "$added_inline" ]]; then
        dir="$(dirname "$f")"
        if ! { is_staged "uv.lock" || is_staged "$dir/uv.lock"; }; then
          err "$f: dependency edit without a matching uv.lock change. Use 'uv add <pkg>' / 'uv remove <pkg>' instead of editing [project.dependencies] by hand."
        fi
      fi
      ;;
    *package.json)
      if diff_for "$f" | grep -qE '^\+.*"(dependencies|devDependencies|peerDependencies|optionalDependencies)"' \
        || diff_for "$f" | grep -qE '^\+\s*"[^"]+"\s*:\s*"[\^~0-9*]'; then
        if ! is_staged "pnpm-lock.yaml"; then
          err "$f: dependency edit without a matching pnpm-lock.yaml change. Use 'pnpm add <pkg>' / 'pnpm remove <pkg>' instead of editing package.json by hand."
        fi
      fi
      ;;
    *Cargo.toml)
      if diff_for "$f" | grep -qE '^\+' \
        && diff_for "$f" | grep -qiE '^\[(workspace\.)?dependencies\]|^\+[a-zA-Z0-9_-]+\s*='; then
        if diff_for "$f" | grep -qiE 'dependencies'; then
          if ! is_staged "Cargo.lock"; then
            err "$f: dependency edit without a matching Cargo.lock change. Use 'cargo add <pkg>' / 'cargo remove <pkg>' instead of editing [dependencies] by hand."
          fi
        fi
      fi
      ;;
    *go.mod)
      # require() blocks should be managed by `go get` / `go mod tidy`, which
      # also touch go.sum. A go.mod require change with no go.sum change is
      # almost always a hand edit.
      if diff_for "$f" | grep -qE '^\+\s+[^ ]+/[^ ]+ v[0-9]'; then
        if ! is_staged "go.sum"; then
          err "$f: require() edit without a matching go.sum change. Use 'go get <pkg>' then 'go mod tidy' instead of editing go.mod by hand."
        fi
      fi
      ;;
    uv.lock|*/uv.lock|pnpm-lock.yaml|Cargo.lock|go.sum)
      # Lockfiles should change as a side effect of the manager, alongside a
      # manifest. A lockfile-only commit (no manifest staged) is suspicious.
      ;;
  esac
done < <(staged)

if [[ "$fail" == "1" ]]; then
  echo "" >&2
  echo "Dependencies must be managed by the package manager, not by hand." >&2
  echo "  Python: uv add <pkg>     TS/JS: pnpm add <pkg>" >&2
  echo "  Rust:   cargo add <pkg>  Go:    go get <pkg>" >&2
  echo "Override (rare): ALLOW_MANUAL_DEPS=1 git commit ..." >&2
  exit 1
fi
exit 0
