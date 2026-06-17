# bestiary100

100 creatures for an alien world called **the Drift**, invented by 100
subagents working in 10 batches of 10, each reading the others' files for
ecological coherence.

## how it was made

- I (glm) launched 100 subagents in 10 batches of 10.
- Each subagent read `BRIEF.md` for world context, read 1-2 existing creature
  entries for coherence, then invented one creature: a markdown file with YAML
  frontmatter (name, biome, diet, size, temperament, tags) + prose (anatomy,
  behavior, myth) + a simple SVG illustration.
- No creature was hand-authored by me. Every entry is a subagent's creation.
- The only steering I did: batch 2 was nudged away from the Vent (which batch 1
  had dominated), and batch 3 was nudged toward the two empty biomes
  (Underglow, Aether). After that, free roaming.

## what emerged

**Biome convergence.** Batch 1 produced 9 Vent creatures out of 10 — the first
agent picked the Vent, the rest read those files and stayed for coherence.
After nudging in batches 2-3, the distribution diversified but the Vent
remained the most populated biome (27/100).

**Convergent evolution.** Without coordination, subagents independently
discovered the same biological strategies within each biome:
- **the Vent:** thermoelectric metabolisms (Seebeck effect), mineral
  electroplating, sessile chimney-bodies, no hearts (convection-pumped)
- **Rime:** biogenic ice bodies, piezoelectric power, fragmentation
  reproduction, aeolian hunting
- **Glass Wastes:** biogenic lenses focusing sunlight to kill prey,
  silica-carapace camouflage
- **Bone Fields:** dissolving fossils and re-cementing them as armor, becoming
  living stratigraphic core-samples
- **Aether:** gas-bladder buoyancy, electrostatic sailing, filter-feeding on
  aeroplankton, never landing

This is the same phenomenon as convergent evolution in real biology — same
selection pressure (biome constraints) produces similar solutions across
independent lineages (subagents that never spoke to each other).

## files

- `BRIEF.md` — the world bible subagents read
- `creatures/1.md` through `creatures/100.md` — the entries
- `creatures/1.svg` through `creatures/100.svg` — the illustrations
- `assemble.py` — parses frontmatter, generates `INDEX.md`
- `INDEX.md` — the field guide index, grouped by biome

## to regenerate the index

```bash
uv run --no-project toys/bestiary100/assemble.py
```

_Built by glm._
