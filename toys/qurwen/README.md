# qurwen

A **phonotactic word generator** for the Qurwenyan conlang. Most toys here take a
word and *render* it; qurwen is the upstream primitive that *invents* the words —
then you can pipe them into glyphgen / phloraflora / phonoscape.

```bash
# one word
uv run python toys/qurwen/main.py
uv run python toys/qurwen/main.py --seed velthar --ipa

# a glossed mini-lexicon (root + derived form + English gloss)
uv run python toys/qurwen/main.py --lexicon 12 --ipa

# tune the shape
uv run python toys/qurwen/main.py -n 8 --syllables 2-4 --ipa --cap

# feed a word straight into a sister toy
uv run python toys/qurwen/main.py --seed ember --cap \
  | xargs -I{} go run ./toys/glyphgen --word {} --out scratch/{}.svg
```

## How it works

- **Inventory.** Weighted phoneme tables (onsets, codas, vowels) each carry a
  romanization *and* an IPA value, so the language has characteristic frequent
  sounds (`q`, `kh`, `th`, liquids) instead of a flat distribution.
- **Syllables.** Built from weighted templates (`CV`, `CVC`, `CCV`, `CVCC`, …).
- **Sonority filter.** Consonant clusters obey a sonority hierarchy: onsets rise
  toward the nucleus (`kr-`, `thl-`, `vr-`), codas fall away from it (`-rn`,
  `-lth`) — so you never get `-tk-` mid-cluster. Diphthong nuclei suppress
  clustering, keeping heavy syllables pronounceable.
- **Stress + IPA.** Primary stress on the first syllable; `--ipa` shows the
  `ˈsyl.la.ble` transcription.
- **Derivation.** `--lexicon` attaches a derivational suffix (place/agent/
  abstract/plural/dimin/of) and an English gloss to each root.

Deterministic: the same `--seed` always yields the same word, so generated words
are stable inputs to the rendering toys. Stdlib only.

## Sample lexicon

```
qunsaq    /ˈqun.saq/   — moth     ~ qunsaqeth (abstract)
pleli     /ˈple.li/    — stone    ~ plelii (plural)
zumothe   /ˈzu.mo.θe/  — bloom    ~ zumotheen (place)
orslamra  /ˈor.slam.ra/ — tide    ~ orslamrael (dimin)
```
