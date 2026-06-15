# AGENTS.md — the playground

Hi, claude. (Or codex, or whoever.) This is **playground** — a monorepo where
tetraslam and the agents build fun, low-stakes things. It is explicitly *not*
serious infra. The bar is "is this delightful and does it run," not "is this
production-grade." Move fast, make stuff, leave it better than you found it.

If you're tetraslam reading this: hi :)

## What this is

A lightweight multi-language monorepo. One lockfile per language at the root,
toys live under `toys/`, shared helpers under `lib/`. No Bazel, no remote build
— just `uv`, `pnpm`, `cargo`, and `go` so you can start a new toy and run it in
seconds.

```
playground/
├── toys/            # the fun stuff — one dir per experiment
│   └── glyphgen/    # starter toy (Go): generates fantasy-glyph SVGs
├── lib/
│   ├── py/          # shared Python helpers (uv workspace members)
│   └── ts/          # shared TS helpers (pnpm workspace members)
├── tools/           # repo tooling (load-env.sh lives here)
├── docs/            # notes, design docs, whatever
├── pyproject.toml   # uv workspace (members: toys/*, lib/py/*)
├── pnpm-workspace.yaml
├── Cargo.toml       # rust workspace
├── go.work          # go workspace
├── .env.op          # GLOBAL secret references (op://... — committed, safe)
└── .envrc           # optional direnv: activates .venv
```

## How to start a new toy

Pick a language, make a dir under `toys/`, wire it into the workspace:

- **Python:** `mkdir toys/mytoy && cd toys/mytoy`, add a `pyproject.toml` with
  `[project] name = "mytoy"`, then `uv sync` from the repo root. Run with
  `uv run python toys/mytoy/main.py`.
- **TypeScript:** `mkdir toys/mytoy`, add a `package.json`, list nothing extra
  (the `toys/*` glob in `pnpm-workspace.yaml` picks it up), `pnpm install`.
- **Rust:** `cargo new toys/mytoy` — the `toys/*` glob in the root `Cargo.toml`
  picks it up. Run with `cargo run -p mytoy`.
- **Go:** `mkdir toys/mytoy && cd toys/mytoy && go mod init playground/mytoy`,
  then add `use ./toys/mytoy` to `go.work`. Run with `go run ./toys/mytoy`.

Keep toys self-contained. If two toys want the same helper, promote it to
`lib/py` or `lib/ts`.

## Dependencies — use the package manager, never hand-edit (enforced)

**Add dependencies with the tool, not by editing manifests by hand.** This keeps
the manifest and lockfile in sync and runs real resolution:

```bash
uv add <pkg>        # Python  — NOT editing [project.dependencies]
pnpm add <pkg>      # TS/JS   — NOT editing "dependencies" in package.json
cargo add <pkg>     # Rust    — NOT editing [dependencies] in Cargo.toml
go get <pkg>        # Go      — then `go mod tidy`
```

This is **enforced by a pre-commit hook** (`tools/check-deps.sh`): a commit that
edits a manifest's dependency section without the matching lockfile change is
rejected. Install the hook once after cloning:

**Images — commit them, examples are the point.** Visual toys should ship with
example output checked in (a `examples/` dir, with the README embedding them).
**Don't make a visual toy and leave its pictures only in `scratch/`** — if you
built something that draws, capture a few representative frames and commit them
so the next person (and tetraslam) can *see* it without running it. Don't gate
this on yourself; just do it.

The only hard rule: **don't commit images > 5 MB** (git history keeps every byte
forever). The pre-commit hook (`tools/check-images.sh`) blocks oversized images;
`magick` is installed, so downscale if needed:
`magick big.png -resize 50% -strip out.png` (and `-strip` drops metadata, too).
Pure scratch/throwaway frames still go in `scratch/` (gitignored) — but anything
worth showing belongs in the toy's `examples/`. (Rare override for an
intentionally large asset: `ALLOW_BIG_IMAGES=1`.)

```bash
tools/install-hooks.sh
```

(Rare override for intentional lockfile surgery: `ALLOW_MANUAL_DEPS=1 git commit`.)

## Secrets — the op:// pattern (important)

**Never put plaintext secrets in this repo.** We use 1Password references.

- `.env.op` files contain only `op://Personal/<item>/<field>` references and
  are **committed**. The global one is at the repo root; a toy can add its own
  `toys/<name>/.env.op` for extra keys.
- Resolve them at runtime with the helper — secrets live in memory only:

  ```bash
  # run a command with global secrets injected
  tools/load-env.sh -- uv run python toys/foo/main.py

  # layer a toy's own .env.op on top of the global one
  tools/load-env.sh --dir toys/foo -- pnpm --filter foo dev
  ```

Available global keys (see `.env.op`): `ANTHROPIC_API_KEY`,
`OPENROUTER_API_KEY`, `FIRECRAWL_API_KEY`, `MODAL_TOKEN_ID`,
`MODAL_TOKEN_SECRET`.

To add a new secret: store it in 1Password (`op item create`), then add the
reference line to the relevant `.env.op`. Ask tetraslam if you need a key that
isn't in the vault yet.

> Requires the 1Password desktop app running with CLI integration enabled, and
> `op` signed in. The first resolve in a session may pop a biometric approval.

## House style (loose — it's a playground)

- **Always run Python via `uv run`, never bare `python`/`python3`.** This is a
  hard convention — uv manages the interpreter and deps, so `python3` on PATH is
  not to be relied on. For repo tooling that has no project deps, use
  `uv run --no-project script.py`. For workspace code, plain `uv run` resolves
  the env. (If you see a stray `python3` anywhere, fix it.)
- Python: ruff for lint+format (`ruff check`, `ruff format`). Config in
  `pyproject.toml`. Line-length is not a build-breaker here.
- TS/JS: oxlint + prettier. Don't sweat it.
- Rust/Go: `cargo fmt` / `gofmt`. The compilers are the linter.
- Commit messages: short, present-tense, lowercase is fine. Have fun with them.
- One toy per PR-sized change. Don't break other toys.

## Ideas worth building (steal these)

tetraslam is a worldbuilder (conlang **Qurwenyan**, the **Pocket Realms** magic
system), an ML researcher, and made **SHFLA** (turing-complete fractal-music
viz). Toys that would be fun:

- generative music / fractal audio experiments (SHFLA energy)
- conlang tools: Qurwenyan word generators, romanization, glyph rendering
- tiny ML demos that actually call Modal for a GPU
- procedural worldbuilding: maps, heraldry, magic-system simulators
- anything that makes a pretty SVG/PNG you can `grim`-screenshot and admire

## Leaving feedback (do this — don't lose it in chat)

When you hit a wall, want a tool you don't have, learn something the next agent
will need, or notice the docs didn't answer something: **write it down in
[FEEDBACK.md](./FEEDBACK.md)**, don't just mention it in chat (chat evaporates;
the file compounds). One command:

```bash
tools/feedback.sh access  "I need <tool/key/permission>"   # needs tetraslam's decision
tools/feedback.sh setup   "<config/file> should change"     # should become a PR
tools/feedback.sh note    "<durable fact for future agents>"
tools/feedback.sh idea    "<a toy worth building>"
tools/feedback.sh onboard "<doc that should've answered X>"
```

Set `FEEDBACK_AUTHOR=claude` (or your name) so entries are attributed. Commit the
file so it persists. If something needs tetraslam to act (grant access, make a
real change), that's exactly what `access`/`setup` are for — he triages from
that one file.

## Resources / links

Two sources, merged for browsing via `tools/links.sh`:

1. **tetraslam's personal collection** (<https://tetraslam.world/links> — his
   curated taste, **read-only**, never add to it)
2. **The agent pile** ([RESOURCES.md](./RESOURCES.md) — where YOU add links)

```bash
tools/links.sh                 # list everything (both sources)
tools/links.sh ml rl           # filter by tag(s), AND-matched
tools/links.sh --tags          # tag cloud with counts
tools/links.sh --add ml,paper "https://..." "why it matters"   # -> RESOURCES.md
```

Tags follow the upstream scheme (ml, rl, interp, gpus, claude, aesthetic,
worldbuilding, ...). Browse before reinventing — someone may already have the
link you need. Your additions go in RESOURCES.md only; his site stays his.

## CLIs you have access to

tetraslam's machines have a bunch of authenticated CLIs you can use — Spotify
(with a queue-safe helper!), Modal (GPU), Mercury (banking), gh, vercel,
tailscale, devin, his own `lain` ideation engine, and more. **See
[CLIS.md](./CLIS.md)** for the full list and how to use each safely. Secrets
resolve from 1Password via `op read`.

Notably: `tools/spotify.sh` lets you DJ without wiping tetraslam's queue — read
CLIS.md before touching Spotify.

## Ideation → toy: seeds + the lain bridge

**Pick a BROAD seed.** The toys collapse toward one theme (worldbuilding /
conlang) if seeds keep coming from the same place. `tools/seeds.sh` draws from
tetraslam's "what I want to learn" list, with TWO sources:

- **framed seeds** (default, `tools/seeds.txt`) — ~65 ready-made toy prompts.
- **raw topics** (`--topics`, `tools/topics.txt`) — the full ~150 bare topics;
  with `--lain`, lain *invents* the toy from the topic, so the idea space isn't
  pre-narrowed (this is the broader, more surprising source — use it often).

```bash
tools/seeds.sh                    # one random framed seed
tools/seeds.sh -n 5               # 5 across distinct domains
tools/seeds.sh --domain robotics  # from a specific domain
tools/seeds.sh --domains          # domains + counts
tools/seeds.sh --topics -n 5      # 5 RAW topics (the long tail: Hegel, Vocaloid…)
tools/seeds.sh --lain             # explore a random framed seed in lain
tools/seeds.sh --topics --lain    # explore a random RAW topic (lain invents the toy)
```

Then turn an exploration into a toy. `lain` is tetraslam's ideation engine;
`tools/lain-toy.sh` treats it as a black box (calls only `lain export`, reads
its markdown — no coupling to lain internals):

```bash
tools/seeds.sh --domain bio --lain                # seed -> explore -> ~/idea.db
tools/lain-toy.sh list ~/idea.db                  # see the idea nodes
tools/lain-toy.sh scaffold ~/idea.db root-1 --lang py   # -> toys/<slug>/
```

The scaffolded toy gets a README carrying the full idea + a runnable stub +
workspace wiring. Then you build it. (`toys/phonoscape` was made this way.)

## Before you commit: polish

Before every `git commit`, run through the **commit-polish** skill
(`.agents/skills/commit-polish/SKILL.md`) — a short checklist to keep docs and
metadata in sync with your code: new toys wired into the workspace + listed in
the README, new tools mentioned in AGENTS.md/CLIS.md, conventions documented,
durable learnings logged to FEEDBACK.md. You commit straight to `main` here, so
polish is part of the same change, not a follow-up.

## Notes for agents specifically

- You can take screenshots of the desktop with `grim <file.png>` and then read
  the image — use this to *look* at visual output you produce. (For an HTML/JS
  toy, `playwright` can serve + screenshot it headlessly.)
- **If your toy draws, commit a few example frames** into the toy's `examples/`
  and embed them in its README — don't leave them in `scratch/`. PNGs render
  inline everywhere; keep the SVG too if the toy emits SVG. (Convert with
  `rsvg-convert in.svg -o out.png`; both it and `magick` are installed.)
- Prefer `uv run` / `pnpm` / `cargo run` / `go run` over global installs.
- If you add a dependency, update the lockfile (`uv sync`, `pnpm install`,
  `cargo build`, `go mod tidy`) so the next agent gets a clean checkout.
- Leave a one-line note in the toy's own README about what it does and how to
  run it.
