---
name: commit-polish
description: Polish your staged changes before committing — update the playground's docs, conventions, and metadata to reflect what you changed. Use right before `git commit`, after the code works. Triggers include "polish before committing", "what should I update before I commit", "make sure this is ready to commit", "update docs for these changes".
---

# commit polish

Before you commit, look at your changes (`git status`, `git diff HEAD`) and make
sure the playground's docs and metadata reflect them. Walk the checklist below,
make the edits, and commit everything together.

This is the playground's analogue of core's `pr-polish`, but it runs **before a
commit** (this repo commits straight to `main`, no PRs) — so you fix things up as
part of the same change, not in a follow-up.

## Checklist

Work through each; skip what doesn't apply.

### 1. New toy? (`toys/<name>/`)
- Does `toys/<name>/README.md` exist with what it is + how to run it?
- Is it wired into its workspace? (Python → `[tool.uv.workspace].members` in
  root `pyproject.toml` + `uv sync`; Go → `go.work`; TS → `pnpm-workspace.yaml`;
  Rust → picked up by the `toys/*` glob.)
- Is the root `README.md` "Toys so far" list updated?

### 2. New tool? (`tools/`)
- Is it mentioned in `AGENTS.md` (and `CLIS.md` if it wraps a CLI)?
- Does it have a one-line usage comment at the top of the script?
- If it runs Python, does it use `uv run` (never bare `python3`)?

### 3. Conventions / metadata
- New convention introduced? Add it to `AGENTS.md` ("House style").
- New enforced rule? Wire it into the pre-commit hook (`tools/`), and document
  it + its override flag in `AGENTS.md`.
- Dependencies added via `uv add`/`pnpm add`/`cargo add`/`go get` (never hand-
  edited)? Lockfile staged alongside?

### 4. Knowledge & ideas
- Learned a durable fact a future agent needs? → `tools/feedback.sh note "..."`.
- Found a useful link? → `tools/links.sh --add <tags> <url> "why"`.
- Hit a wall / want access? → `tools/feedback.sh access "..."`.
- Built a toy that came from an idea in `FEEDBACK.md`? Mark it/move it.

### 5. Hygiene
- Generated images in `scratch/` (gitignored), none > 5 MB committed.
- No stray `python3` (use `uv run`); no plaintext secrets (use `op://`).
- Commit message is short, present-tense, and matches the repo style.

## Do not
- Don't rewrite code or fix bugs here — polish is docs/metadata only.
- Don't create new top-level docs unless the checklist calls for it; prefer
  updating existing ones (AGENTS.md, CLIS.md, READMEs).
- No emoji in docs unless asked.
