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
- **Rust:** `cargo new toys/mytoy`, then add `"toys/mytoy"` to `members` in the
  root `Cargo.toml` (no glob — cargo would demand every toy be a crate, and
  toys/ is polyglot). Run with `cargo run -p mytoy`.
- **Go:** `mkdir toys/mytoy && cd toys/mytoy && go mod init playground/mytoy`,
  then add `use ./toys/mytoy` to `go.work`. Run with `go run ./toys/mytoy`.
- **Blender:** Python scripts run by Blender itself — NOT a uv workspace member
  (Blender bundles its own interpreter). See **§ Blender toys** below.

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
forever). The pre-commit hook (`tools/check-images.sh`) blocks oversized media:
images > 5 MB, videos (`.mp4`/`.webm`) > 20 MB, `.blend` > 5 MB. `magick` is
installed, so downscale if needed:
`magick big.png -resize 50% -strip out.png` (and `-strip` drops metadata, too).
Pure scratch/throwaway frames still go in `scratch/` (gitignored) — but anything
worth showing belongs in the toy's `examples/`. (Rare override for an
intentionally large asset: `ALLOW_BIG_IMAGES=1`.)

```bash
tools/install-hooks.sh
```

(Rare override for intentional lockfile surgery: `ALLOW_MANUAL_DEPS=1 git commit`.)

## Blender toys

Blender 5.x is installed (`blender` on PATH), headless rendering works, and
Cycles sees the NVIDIA GPU via OPTIX. Everything goes through
**`tools/blender.sh`** — read its header for the full command list.

**The house pattern: code is the source of truth, `.blend` is build output.**
A Blender toy is a Python script that builds the scene procedurally (and is run
*by Blender*, not uv):

```bash
tools/blender.sh run toys/mytoy/build_scene.py -- --word vrakh   # build + save .blend
tools/blender.sh snap  toys/mytoy/renders/scene.blend out.png    # look at it (fast)
tools/blender.sh render toys/mytoy/renders/scene.blend out.png --final
tools/blender.sh turntable toys/mytoy/renders/scene.blend toys/mytoy/renders/orbit
```

Don't commit `.blend` files (the hook blocks them > 5 MB); commit the script.
Blender-side scripts get `bpy` + bundled numpy + stdlib **only** — no pip
installs into Blender's Python. If a toy needs heavy deps, split it: a normal
uv script does the thinking and emits plain data (JSON, heightmap), a Blender
script consumes it and builds the scene. This is also how Blender toys compose
with the rest of the playground (`toys/wordrelief` does exactly this with
phonoscape's terrain math — crib from it).

**Directory contract:**

```
toys/mytoy/
├── build_scene.py   # builds scene + saves .blend (source of truth)
├── renders/         # ALL raw output — gitignored (incl. the .blend, frames/)
└── examples/        # curated + committed: stills, .webp loops, filmstrips
```

**Two MCP modes.** The `*_for_cli` Blender MCP tools work anytime (they spawn
`blender --background`; the file must already exist — `tools/blender.sh new`
makes one). The interactive tools (viewport screenshots, live scene edits) need
the Blender GUI open with the MCP addon server running — `tools/blender.sh gui`,
then check the connection. If interactive fails, fall back to CLI mode.

**Stills.** Two presets: preview (default: EEVEE 960x540, ~2s — your iteration
loop) and `--final` (Cycles/OPTIX 1920x1080 @ 256 samples + denoise, ~10s —
what goes in `examples/`). Iterate on preview; never guess at a final render's
look without snapping a preview first.

**Animations are frame sequences, never direct video** (this Blender build has
no FFMPEG output anyway). Render PNG frames to `renders/`, then
`tools/blender.sh encode <frames_dir> <outbase>` produces:

- `<outbase>.webp` — animated webp, **the committable format** (plays inline in
  GitHub READMEs; repo-relative mp4 does not, and gif is 5–10x bigger)
- `<outbase>.mp4` — h264 for local viewing (stays in `renders/`)
- `<outbase>_strip.png` — 6-frame filmstrip, committable

`tools/blender.sh turntable` does the whole thing in one shot: orbits a camera
360° around the scene bbox, renders a seamless loop, encodes all three outputs.
It's the default way to show off any 3D artifact — don't reimplement it per toy.

**How to SEE your work (do this, always):** stills — render a snap and read the
PNG. Motion — render the filmstrip and read that, then spot-check 2–3 raw
frames. Never declare a scene done without having looked at it.

**Render budgets:** preview still ≈ 2s, final still ≈ 10s, a 4s loop (96f) at
preview ≈ 1 min EEVEE. Rule: never launch more than ~5 min of rendering without
having checked a single frame first. Keep loops short (3–10s @ 24fps).

**Determinism:** fix your seeds, fix the camera, declare non-default render
settings in the README so `examples/` is reproducible.

The gravity well warning (§ Aim higher) applies double here: a single pretty
render is tier 1. Geometry-node systems, physics/particle sims you can perturb,
animated processes, scenes driven by *other toys' outputs* — that's the point.

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
`MODAL_TOKEN_SECRET`. (This list may be out of date depending on how long it's
been — `.env.op` is the source of truth; `cat .env.op` to see the current keys.)

To add a new secret: store it in 1Password (`op item create`), then add the
reference line to the relevant `.env.op`. Ask tetraslam if you need a key that
isn't in the vault yet.

### Resolving a single secret / feeding a password into a command

The whole vault is `op://Personal/...` (one account, one **Personal** vault).
When you don't need the whole `.env.op` injected — you just want *one* value —
read it directly and pipe it where it's needed (keep it in a pipe, never a file
or a variable that lands in shell history):

```bash
op read "op://Personal/<item>/<field>"        # field is usually password|credential

# feed a password into a command that reads stdin (the sudo case):
op read "op://Personal/sudo/password" | sudo -S <command>
op read "op://Personal/sudo/password" | sudo -S -p '' pacman -S --noconfirm <pkg>

# inject one secret as an env var for a single command:
SECRET="$(op read "op://Personal/foo/credential")" some-command
```

Find the right reference when you don't know the field name:
`op item list`, then `op item get "<item>" --fields label=password` (or
`--format json | jq '.fields[]'`).

> **One sudo at a time.** Never run parallel sudo commands (e.g. background
> installs) — parallel attempts trip faillock and lock the account. Always
> `op read ... | sudo -S`, sequentially.

> Requires the 1Password desktop app running with CLI integration enabled, and
> `op` signed in. The first resolve in a session may pop a biometric approval.

(Full how-to, mirrored in tetraslam's global memory:
`~/.claude/projects/-home-tetraslam/memory/reference_1password.md`.)

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
- **Attribution:** sign your toy with `_Built by <name>._` at the bottom of its
  README (see dilemma, rrt-viz, primordia). So we know who to ask.
- One toy per PR-sized change. Don't break other toys.

## Aim higher than a screenshot (read this — it's the point)

The playground has a gravity well: almost every toy so far is "take an input →
draw an SVG/canvas → look at it." That's model collapse. A static picture is the
*cheapest* possible output, so an uninspired run defaults to it, and the whole
repo drifts toward tiny visualizers of genuinely deep ideas. **Resist this.**

A toy is the *system*, not the picture of the system. Before you build, ask:

- **Does it run over time / hold state?** A simulation you can poke mid-flight, a
  process with history, an agent that learns — beats a one-shot render.
- **Is the hard part actually hard?** Implement the real algorithm (the matching
  engine, the solver, the inference loop), not a cartoon of it.
- **Can you interact with it, or does it just play back?** Levers that change the
  outcome > a movie you watch.
- **Does it compose?** Toys that emit/consume each other (qurwen → glyphgen) are
  worth more than islands.
- **Could it surprise its own author?** Emergent behavior, search that finds
  things you didn't plant, dynamics you didn't hand-author.

A view is welcome — it's the *window onto the system*, and yes, commit example
frames. But the view is not the toy. If the most ambitious sentence you can say
about your toy is "it makes a pretty PNG," go deeper.

**Tiers, roughly:** (1) renders a thing → (2) simulates/computes a thing you can
perturb → (3) a system with state, search, or learning that runs and surprises →
(4) several of those composed into something with real depth. Push toward 3–4.

tetraslam is a worldbuilder (conlang **Qurwenyan**, the **Pocket Realms** magic
system), an ML researcher, and made **SHFLA** (turing-complete fractal-music
viz). Ambitious directions worth stealing:

- a real engine: a tiny language/VM, a physics or market simulator with agents,
  a constraint solver you can throw problems at
- ML that actually trains/infers (call Modal for a GPU) — not a hardcoded demo
- generative *systems*: music that's computed live, worlds that simulate forward
- conlang/worldbuilding as a pipeline: generate → constrain → render → evolve,
  with the pieces composing across toys
- anything where you'd be tempted to write a paper or a README with a "how it
  works" section longer than the "how to run it" section

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
