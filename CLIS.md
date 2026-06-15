# CLIS.md — command-line tools available to agents

Tools installed on tetraslam's machines (`tetrabot` / `tetrabot-2`) that agents
can use. Secrets for these live in 1Password — resolve with
`op read "op://Personal/<item>/credential"` (see AGENTS.md), never hardcode.

> Two laptops, used equally (home vs work/out). Run `hostname` to see which
> you're on; the other is reachable over ssh (`ssh tetrabot-2` / `ssh tetrabot`).
> Not every CLI is on both — check before assuming.

## Music — Spotify 🎵 (read the queue rule!)

**THE RULE: tetraslam almost always has a queue going. Do NOT clobber it.**
To play something, *append it to the queue* — never "start playback", which
replaces the current context and wipes the queue. Always read the queue first.

Use the helper `tools/spotify.sh` — it bakes in the safe behavior:

```bash
tools/spotify.sh now                 # what's playing
tools/spotify.sh queue               # show the current queue
tools/spotify.sh search "<query>"    # search tracks -> "id  name — artist"
tools/spotify.sh add "<query>"       # SAFE: append best match to queue
tools/spotify.sh add-id <track_id>   # SAFE: append a known id
tools/spotify.sh play|pause|next|prev
tools/spotify.sh vol <0-100>
tools/spotify.sh replace "<query>"   # ⚠ DANGER: wipes queue, starts fresh
```

Under the hood: `spotify_player` (CLI, JSON output, Premium, already authed) for
reads/transport, and the Spotify Web API `POST /me/player/queue` (via the token
`spotify_player` caches at `~/.cache/spotify-player/user_client_token.json`) for
queue-safe appends — because `spotify_player`'s own play commands only *replace*
context. `playerctl -p spotify ...` also works for basic MPRIS transport.

## Cloud / infra

- **modal** — serverless GPU/compute. `modal run`, `modal deploy`, `modal app
  list`. Tokens in 1Password (`MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`); the CLI
  also has its own cached auth. The whole point of GPU toys — use it.
- **vercel** — deploy/preview web projects. `vercel`, `vercel deploy`,
  `vercel env`. (pnpm global.)
- **tailscale** — the tailnet linking the laptops + homelab. `tailscale status`,
  `tailscale ip`. Read-only checks are safe.
- **op** — 1Password CLI. `op read`, `op item get/create`. The source of truth
  for every secret. Desktop app integration → biometric approval prompts.
- **mullvad** — VPN. `mullvad status`, `mullvad connect/disconnect`.

## Banking — Mercury 💸 (careful)

- **mercury** — Mercury bank CLI (`~/.local/bin/mercury`, already authed).
  Read freely: `mercury accounts`, `mercury transactions`, `mercury statements`.
  Money-moving verbs (`mercury payments`, `mercury recipients`) touch real funds
  — tetraslam has account-level guardrails, but still: surface what you're about
  to do, and don't use `-y` on a send unless explicitly told. Use
  `--environment sandbox` for testing.

## Dev / build

- **gh** — GitHub CLI, authed as `Tetraslam` (repo, workflow, gist, read:org).
  Issues, PRs, releases, repo create. Full access — use it.
- **go** / **cargo** / **zig** / **nim** — compilers, all present. (Go is the
  glyphgen toy's language.)
- **signal-cli** — Signal from the terminal (`~/signal-cli/bin/signal-cli`).
  Send/receive messages, manage groups.
- **mosh** — resilient SSH (`mosh tetrabot-2`) for flaky connections.
- **publish-blog** — tetraslam's blog publishing helper.

## Agents (tetraslam runs a whole stable)

- **devin** — Cognition's terminal+cloud agent, authed. `devin -p "<prompt>"`
  for non-interactive, `devin cloud` to hand off to the cloud.
- Others on the machines: `codex`, `gemini`, `copilot`, `pi`, `opencode`.

## lain — tetraslam's own ideation engine 🌀

- **lain** (`Programming/lain`, github.com/Tetraslam/lain) — a graph-based
  ideation engine. Seed an idea, branch into n children, recurse to depth m; an
  LLM expands each node, then a synthesis pass traverses the DAG to surface
  cross-links, contradictions, and emergent patterns. Named after Lain Iwakura.

  ```bash
  lain "your idea" --n 3 --m 2
  ```

  Bun monorepo (pnpm + turbo), built-in extensions: freeform, worldbuilding,
  debate, research. Uses AWS Bedrock via bearer token. Genuinely useful for
  brainstorming toys/worldbuilding — try it.
