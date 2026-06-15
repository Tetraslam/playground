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

## Notes for agents specifically

- You can take screenshots of the desktop with `grim <file.png>` and then read
  the image — use this to *look* at visual output you produce.
- Prefer `uv run` / `pnpm` / `cargo run` / `go run` over global installs.
- If you add a dependency, update the lockfile (`uv sync`, `pnpm install`,
  `cargo build`, `go mod tidy`) so the next agent gets a clean checkout.
- Leave a one-line note in the toy's own README about what it does and how to
  run it.
