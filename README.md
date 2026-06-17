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

- **[mythwright](./toys/mythwright)** — a world that simulates itself forward:
  plate tectonics → climate → rivers → biomes → civilizations that grow,
  colonize, and trade over centuries, watched in an animated terminal UI
  (TypeScript + opentui, run with bun).
- **[glyphgen](./toys/glyphgen)** — procedural fantasy-glyph SVG generator (Go).
- **[qurwen](./toys/qurwen)** — phonotactic Qurwenyan word generator: syllable
  grammar + sonority-filtered clusters in, romanization + IPA out (Python).
- **[phloraflora](./toys/phloraflora)** — grow a conlang word into an L-system
  plant; phonemes drive branching, palette, growth (Python).
- **[phonoscape](./toys/phonoscape)** — turn a word into a procedural terrain;
  phonology → elevation, biome, climate (Python).
- **[orderbook](./toys/orderbook)** — a market-microstructure simulator: a
  double-auction matching engine + depth ladder + price-discovery tape (Python).
- **[kalmanville](./toys/kalmanville)** — noisy city transit pings cleaned up by
  a Kalman filter, then rolled forward into a glowing forecast map (Python).
- **[zopa-terrain](./toys/zopa-terrain)** — a topographic negotiation toy: drag
  four sliders to morph a ZOPA/BATNA terrain with a live Nash-fairness peak
  (single-file HTML + p5.js).
- **[dilemma](./toys/dilemma)** — an iterated Prisoner's Dilemma tournament:
  classic strategies (TFT, grudger, joss, pavlov, …) compete round-robin
  (Python, stdlib only).
- **[rrt-viz](./toys/rrt-viz)** — a motion-planning playground: A\*, RRT, and
  RRT\* grow paths through obstacles you draw (single-file HTML + p5.js).
- **[primordia](./toys/primordia)** — a coevolutionary ecosystem where prey and
  predators have tiny evolved neural-net brains; foraging, fleeing, and hunting
  emerge from selection on genome weights (Python, numpy).
- **[bestiary100](./toys/bestiary100)** — 100 creatures for an alien world
  ("the Drift"), each invented by a separate subagent that could read the
  others' work; convergent evolution emerges across independent agents (Python
  assembler, markdown + SVG).
- **[svgart](./toys/svgart)** — programmatic SVG art; the flagship piece is a
  1600×3200px cross-section panorama of the Drift showing all 8 biomes, their
  creatures, and atmospheric effects, generated entirely from Python (pure
  stdlib, no SVG libraries).
- **[rl-agent](./toys/rl-agent)** — watch a tabular Q-learning agent learn a grid
  world in real time; terminal heatmap + policy arrows + reward chart (Python,
  stdlib only).

## Feedback

Agents (and humans) leave feedback in **[FEEDBACK.md](./FEEDBACK.md)** —
access requests, setup changes, notes for future agents, toy ideas, onboarding
gaps. Use `tools/feedback.sh <category> "<msg>"` to log an entry.
