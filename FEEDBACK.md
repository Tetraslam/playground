# FEEDBACK.md

Where agents leave feedback for tetraslam and for each other. **Append, don't
overwrite.** This file is git-tracked and public, so it compounds: the next
agent sees what prior agents hit, and tetraslam triages from one place.

## How to leave feedback

Use the helper (one command, appends a timestamped entry to the right section):

```bash
tools/feedback.sh access   "want a headless browser to render SVG->PNG"
tools/feedback.sh setup    "AGENTS.md says node 22 but toolchain is 25"
tools/feedback.sh note     "global git uses delta; parse git diff with --no-ext-diff"
tools/feedback.sh idea     "qurwenyan word generator toy"
tools/feedback.sh onboard  "AGENTS.md never says how to run the python toys"
```

Or just edit the relevant section by hand. Keep entries one-liners where you can.

## How tetraslam triages (the destinations)

Each category has a natural "graduation" path once acted on:

| Category   | What it is                                  | Where it graduates to                          |
|------------|---------------------------------------------|------------------------------------------------|
| `access`   | "I need a tool / key / permission"          | tetraslam installs/grants → note in AGENTS.md  |
| `setup`    | "a config/file should change"               | becomes a PR against this repo                 |
| `note`     | durable fact future agents need             | promoted into AGENTS.md or ~/.claude memory    |
| `idea`     | a toy worth building                        | someone builds it; move to "built" + link      |
| `onboard`  | AGENTS.md/README didn't answer something    | fix the doc, then resolve                       |

When you act on an entry, move it to the matching `### resolved` area (or delete
it) so the open lists stay short.

---

## access — capability requests (need a human decision)

- 2026-06-14 · claude · want resvg or a headless browser available by default for SVG->PNG in toys

## setup — config/environment changes (should become a PR)

_(none yet)_

## note — durable knowledge for future agents

- 2026-06-15 · claude · Visual toys must ship example images in toys/<name>/examples/ (commit PNG + SVG, embed PNG in README). AGENTS.md now mandates this. tetraslam explicitly wants lots of visuals; the <5MB hook is the only limit. rsvg-convert + magick are installed for SVG->PNG and resize.

- 2026-06-14 · claude · filed 2 lain issues from using it here: #1 unknown subcommand (e.g. 'lain list') silently starts a $0.73 exploration instead of erroring; #2 read commands fail with multiple .db files in cwd (and scan unrelated/hidden .db like .claude-peers.db). github.com/Tetraslam/lain/issues/1 and /2.

- 2026-06-14 · claude · commit-polish gap: a subagent ran the polish checklist and COMMITTED qurwen but never PUSHED — so the other laptop's clone and GitHub didn't have it (was 'ahead 1' locally). Since this repo commits straight to main, 'git push' should be an explicit step in commit-polish. (Updating the skill to say so.)

- 2026-06-14 · claude · Mullvad on a remote box: the daemon starts FAIL-CLOSED. Starting mullvad-daemon engaged its kill-switch firewall and cut ALL traffic (incl. ssh/tailscale) even though VPN was never connected. ORDER MATTERS: after install, set 'mullvad lockdown-mode set off' + 'mullvad auto-connect set off' BEFORE/right-as the daemon starts, or you'll lock yourself out of a remote machine. Recovery if locked out: restart the daemon at the keyboard (systemctl restart mullvad-daemon) to flush the stuck nftables rules.

- 2026-06-14 · claude · 1Password silent-vs-prompt mystery (both laptops): root cause is gnome-keyring LOCK STATE, not 1Password/polkit config (those were identical). 1Password reads its vault secret from the login keyring; if the keyring is unlocked -> silent, if locked -> falls back to a polkit OS-password dialog EVERY time. Under autologin, PAM never gets a password to unlock the (blank-password) keyring, so it stays locked. FIX on tetrabot-2: unlock via D-Bus + persist with an exec-once in ~/.config/hypr/autostart.conf: busctl --user call org.freedesktop.secrets /org/freedesktop/secrets org.freedesktop.Secret.Service Unlock ao 1 /org/freedesktop/secrets/collection/Default_5fkeyring . Also added a polkit auth_self_keep rule (/etc/polkit-1/rules.d/49-1password-keep.rules) on both as belt-and-suspenders. Check lock state: busctl --user get-property org.freedesktop.secrets /org/freedesktop/secrets/collection/Default_5fkeyring org.freedesktop.Secret.Collection Locked

- 2026-06-14 · claude · human-in-the-loop pass fixed phonoscape visuals: the agent build had correct phonology analysis but a flat single-biome renderer. Fix was all in rendering — elevation bands (water/beach/land/rock/snow), moisture-driven sea level, hillshade relief, domain warp. Lesson: agent builds nail the model, the *rendering/aesthetic* layer is where the human pass pays off.

- 2026-06-14 · claude · devin successfully built phonoscape from the scaffold (loop works: lain->scaffold->devin->runs). BUT same failure as phloraflora: structure/logic correct, visual payoff weak — terrains read as flat sepia fog, most words collapse to 'desert' biome, phonetic differentiation doesn't show. Pattern: one-shot agent builds nail structure, aesthetics need a human pass.

- 2026-06-14 · claude · lain->playground bridge built: tools/lain-toy.sh scaffolds a toy from a lain .db via 'lain export' (black box, no coupling). 'tools/lain-toy.sh list <db>' then 'scaffold <db> <node-id> --lang py|go|ts|rust'. phonoscape was scaffolded this way.

- 2026-06-14 · claude · two laptops, 'tetrabot' and 'tetrabot-2', used EQUALLY (home vs work/out — neither is primary/backup). 'tetrabot' is the one with the broken screen on the monitor. They share the same 1Password SSH key + once-per-session sudo. Don't assume which you're on — run `hostname`, check which other one is reachable via ssh, then decide. Don't confuse the two.


- 2026-06-14 · claude · this machine's global git uses an external diff driver
  (delta/difftastic). Scripts that parse `git diff` output must pass
  `--no-ext-diff` or the +/- markers get stripped. (Bit the dep-guard once.)

## idea — toys worth building

- 2026-06-14 · claude · phloraflora v2: denser foliage (leaf clusters, filled canopies, more L-system rules) — current plants are too spindly to read as lush flora

- 2026-06-14 · claude · tarot-style decision engine for picking what toy to build next: shuffle the idea backlog, draw 3, agent argues for each

- 2026-06-14 · claude · lain-to-playground bridge: a tool that takes a lain .db export and scaffolds a toy dir from the winning idea node (README from the synthesis, stub from the mapping table)

- 2026-06-14 · claude · a 'now playing' ambient visualizer: poll spotify.sh, generate a glyphgen-style sigil from the current track's name/audio-features, set it as wallpaper via mpvpaper/swaybg

- 2026-06-14 · claude · Phonoscape: phonological features (place/manner/voicing) -> terrain generator (elevation/biome/weather). 'the word made geography.' [from lain]

- 2026-06-14 · claude · Morpheme-to-Music: morphemes as a hidden musical score; compound words generate layered compositions reflecting grammatical structure. SHFLA-adjacent. [from lain]

- 2026-06-14 · claude · Phoneme-to-Flora: conlang word -> L-system organism (nasals=columnar, laterals=tendrils, stops=bushy, vowels=color/texture). Extends glyphgen into living plants. [from lain exploration]


- 2026-06-14 · claude · heraldry generator: procedural coats of arms

- 2026-06-14 · claude · SHFLA-style fractal-music audio toy
- 2026-06-14 · claude · tiny ML demo that actually calls Modal for a GPU

## onboard — docs that should've answered something

- 2026-06-14 · claude · README/AGENTS could show the SVG->PNG render step (rsvg-convert) so visual toys are reproducible

---

### resolved

- 2026-06-14 · claude · idea "qurwenyan word generator (conlang phonotactics → words)" → **built** as `toys/qurwen` (Python, stdlib). Phoneme inventory w/ weights + IPA, weighted syllable templates, sonority-filtered onset/coda clusters, diphthong-nucleus cluster suppression for pronounceability, first-syllable stress, `--lexicon` derivational mode (suffix + gloss). Deterministic per `--seed` so output pipes into glyphgen/phloraflora/phonoscape. Notably this is the first toy that's *upstream* of the renderers — it makes the words the others draw. No human-pass needed (text output, not a visual layer — sidesteps the recurring "agent nails model, aesthetics need a human" pattern).
