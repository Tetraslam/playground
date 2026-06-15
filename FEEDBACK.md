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

- 2026-06-14 · claude · two laptops, 'tetrabot' and 'tetrabot-2', used EQUALLY (home vs work/out — neither is primary/backup). 'tetrabot' is the one with the broken screen on the monitor. They share the same 1Password SSH key + once-per-session sudo. Don't assume which you're on — run `hostname`, check which other one is reachable via ssh, then decide. Don't confuse the two.


- 2026-06-14 · claude · this machine's global git uses an external diff driver
  (delta/difftastic). Scripts that parse `git diff` output must pass
  `--no-ext-diff` or the +/- markers get stripped. (Bit the dep-guard once.)

## idea — toys worth building


- 2026-06-14 · claude · heraldry generator: procedural coats of arms

- 2026-06-14 · claude · qurwenyan word generator (conlang phonotactics → words)
- 2026-06-14 · claude · SHFLA-style fractal-music audio toy
- 2026-06-14 · claude · tiny ML demo that actually calls Modal for a GPU

## onboard — docs that should've answered something

- 2026-06-14 · claude · README/AGENTS could show the SVG->PNG render step (rsvg-convert) so visual toys are reproducible

---

### resolved

_(move acted-on entries here with a one-line outcome)_
