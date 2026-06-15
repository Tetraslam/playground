# phloraflora

Grow a conlang word into an L-system plant, rendered as SVG. Every phoneme is a
biological instruction — the word's sounds drive branching angle, segment
length, recursion depth, stochastic variance, and palette. Same word → same
plant.

```bash
uv run python toys/phloraflora/main.py --word veltharion --out scratch/vel.svg
uv run python toys/phloraflora/main.py --word gox --size 600
```

## The mapping (phoneme → biology)

- **nasals** (m n ŋ) → narrow branching → upright, columnar forms
- **laterals/approximants** (l r w j) → longer segments → elongated, trailing
- **stops** (p t k b d g) → wide branching → bushier canopy
- **fricatives** (s z f v) → stochastic variance → wind-shaped asymmetry
- **velars** (k g q) → shorter segments → compact growth
- **voiced** consonants → +recursion depth → more complex
- **vowels** → palette: front (i e) = luminous greens; back (a o u) = dark olive

So a word's *phonaesthetics* shape a plant that feels native to it — and words
sharing sounds grow visually-rhyming flora (a biome signature).

Idea seeded by a `lain` exploration ("Phoneme-to-Flora"). Stdlib only; render
SVG→PNG with `rsvg-convert` to view.

## Known v2 work

Currently a bit spindly — the L-system needs denser foliage (leaf clusters,
filled canopies, more branch rules) to read as lush flora. The mapping logic and
determinism work; it's the visual richness that wants another pass.
