#!/usr/bin/env bash
# install-hooks.sh — wire up the repo's git hooks. Run once after cloning.
#
#   tools/install-hooks.sh
#
# Points git at the version-controlled hooks in tools/hooks/ so every
# contributor (and agent) gets the dependency guard automatically.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
git config core.hooksPath tools/hooks
chmod +x tools/hooks/* tools/*.sh 2>/dev/null || true
echo "✓ git hooks installed (core.hooksPath = tools/hooks)"
echo "  pre-commit will block hand-edited dependencies. Use uv/pnpm/cargo/go."
