# playground

A lightweight multi-language monorepo where [tetraslam](https://github.com/Tetraslam)
and the agents (claude, codex, whoever) build fun, low-stakes things.

Not serious infra. The bar is "is this delightful and does it run." Move fast,
make stuff.

## Layout

```
toys/        # the fun stuff — one dir per experiment
lib/py·ts    # shared helpers, promoted out of toys when reused
tools/       # repo tooling (env injection, dep guard, git hooks)
docs/        # notes & design docs
```

One lockfile per language at the root: `uv` (Python), `pnpm` (TS/JS), `cargo`
(Rust), `go.work` (Go). Start a new toy in seconds — see **[AGENTS.md](./AGENTS.md)**.

## Quickstart

```bash
tools/install-hooks.sh          # wire up git hooks (do this once)
go run ./toys/glyphgen --word Qurwenya --out scratch/qurwenya.svg
```

## Two rules

1. **Secrets** never live in plaintext here. Commit `op://` references in
   `.env.op`, resolve at runtime: `tools/load-env.sh -- <cmd>`. See AGENTS.md.
2. **Dependencies** are added with the package manager (`uv add`, `pnpm add`,
   `cargo add`, `go get`) — a pre-commit hook blocks hand-edited manifests.

## Toys so far

- **[glyphgen](./toys/glyphgen)** — procedural fantasy-glyph SVG generator (Go).
- **[qurwen](./toys/qurwen)** — phonotactic Qurwenyan word generator: syllable
  grammar + sonority-filtered clusters in, romanization + IPA out (Python).

## Feedback

Agents (and humans) leave feedback in **[FEEDBACK.md](./FEEDBACK.md)** —
access requests, setup changes, notes for future agents, toy ideas, onboarding
gaps. Use `tools/feedback.sh <category> "<msg>"` to log an entry.
