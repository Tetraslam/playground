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
tools/spotify.sh token-check         # verify the cached token still works
```

Under the hood (rewritten 2026-06): **everything** goes through the Spotify Web
API using the OAuth token `spotify_player` caches at
`~/.cache/spotify-player/user_client_token.json` (auto-refreshed; carries every
scope incl. `user-modify-playback-state` + `user-read-playback-state`). The
helper deliberately does **not** depend on the `spotify_player` *daemon* being
connected as a device — that daemon is fragile and often has no cached
credentials (`Error: try to connect to a client`), which used to break `now` /
`queue` / `search`. The Web API works whenever *any* device is active (phone,
desktop app, the other laptop). `playerctl -p spotify ...` (MPRIS) is used only
as a local fallback for `now`. If reads suddenly fail, run `token-check`; if the
token cache is gone, launch `spotify_player` once to re-auth and repopulate it.

## Cloud / infra

- **modal** — serverless GPU/compute. `modal run`, `modal deploy`, `modal app
  list`. Tokens in 1Password (`MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`); the CLI
  also has its own cached auth. The whole point of GPU toys — use it.
- **vercel** — deploy/preview web projects. `vercel`, `vercel deploy`,
  `vercel env`. (pnpm global.)
- **tailscale** — the tailnet linking the laptops + homelab. `tailscale status`,
  `tailscale ip`. Read-only checks are safe.
- **op** — 1Password CLI. The source of truth for every secret (one **Personal**
  vault). `op read "op://Personal/<item>/<field>"` resolves one value;
  `op item list` / `op item get` find references. Feed a password straight into a
  command's stdin instead of hardcoding — e.g. sudo:
  `op read "op://Personal/sudo/password" | sudo -S <cmd>` (one sudo at a time —
  parallel sudo trips faillock). Desktop app integration → biometric prompts.
  Full how-to in AGENTS.md (§Secrets) and `reference_1password.md` in global
  memory.
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
- **blender** — Blender 5.x, headless-capable, Cycles renders on the NVIDIA GPU
  (OPTIX). Use `tools/blender.sh` (new/run/render/snap/turntable/encode/gui)
  rather than raw flags — see AGENTS.md § Blender toys. The Blender MCP's
  `*_for_cli` tools work anytime; interactive tools need the GUI open with the
  MCP addon server running.
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
  lain "your idea" --n 3 --m 2          # inline seed (multi-word)
  lain explore "your idea" --n 3 --m 2  # explicit form — use for one-word seeds
  ```

  Note: a single-word seed that looks like a subcommand (e.g. `lain list`) now
  errors with a "did you mean" instead of exploring (bareword guard). Use the
  explicit `lain explore "<seed>"` escape hatch when scripting seeds that might
  be one word — `tools/seeds.sh` already does.

  Bun monorepo (pnpm + turbo), built-in extensions: freeform, worldbuilding,
  debate, research. Uses AWS Bedrock via bearer token. Genuinely useful for
  brainstorming toys/worldbuilding — try it.
