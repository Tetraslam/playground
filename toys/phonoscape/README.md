# phonoscape

> A conlang word is not just a sequence of phonemes — it is a physical event. To say *vrakh* is to put teeth against lip, to vibrate the cords, to release air in a burst. Those articulatory gestures carry measurable, categorizable properties: place of articulation, manner, voicing, vowel height, vowel backness, syllable length. The **Phonoscape** tool treats those properties as literal terrain parameters, feeding them into a procedural landscape generator so that the land you see is the word made geography.

_Scaffolded from a `lain` exploration node (`root-3`). The design below is the idea — go build it._

## The Core Premise

A conlang word is not just a sequence of phonemes — it is a physical event. To say *vrakh* is to put teeth against lip, to vibrate the cords, to release air in a burst. Those articulatory gestures carry measurable, categorizable properties: place of articulation, manner, voicing, vowel height, vowel backness, syllable length. The **Phonoscape** tool treats those properties as literal terrain parameters, feeding them into a procedural landscape generator so that the land you see is the word made geography.

---

## The Phonology-to-Parameter Mapping

Every phoneme along the IPA chart carries three orthogonal features that translate naturally into terrain axes:

### Consonants → Terrain Texture & Drama

| Phonological Feature | Terrain Mapping | Why It Holds |
|---|---|---|
| **Voiceless plosives** (/p/, /t/, /k/) | High noise lacunarity, sharp ridgelines, escarpments | The sudden air-burst mirrors abrupt elevation change |
| **Voiced fricatives** (/v/, /ð/, /z/) | Gradual erosion scarps, canyon lips, wind-smoothed plateaus | Continuous turbulent air flow → continuous texture |
| **Nasals** (/m/, /n/, /ŋ/) | Rolling hills, basin topography, humid valleys | Nasal resonance is low-frequency, sustained; basins collect |
| **Liquids & laterals** (/l/, /r/) | River deltas, meandering floodplains, broad estuaries | The trill of /r/ tracks roughness; /l/'s lateral flow is riverine |
| **Sibilants** (/s/, /ʃ/) | Windswept dunes, talus slopes, sand plains | Hissing turbulence = granular, high-frequency surface variation |
| **Glottals & uvulars** (/h/, /χ/, /ʁ/) | Volcanic caldera, deep rift valleys | Produced in the throat's depth → geological depth features |

**Place of articulation** contributes a second axis: bilabials produce low Perlin octave counts (gentle, rounded hills — the bouba effect in topography), while velars and uvulars push the generator toward jagged ridgelines and deep elevation deltas.

### Vowels → Climate, Moisture & Biome Temperature

The vowel quadrilateral maps directly onto a two-axis biome chart. High front vowels like /i/ are cold and dry (alpine tundra); low back vowels like /ɑː/ are warm and wet (rainforest). This is not arbitrary — the bouba/kiki research shows /i/ is consistently experienced as sharp, small, cold, fast, while /a/ and /o/ are large, warm, rounded. Vowel length adds a temporal modifier: long vowels stretch the climate zone across more terrain tiles.

| Vowel Class | Temperature | Moisture | Archetypal Biome |
|---|---|---|---|
| High-front /i/, /ɪ/ | Cold | Low | Tundra, snow waste |
| High-back /u/, /ʊ/ | Cold | High | Taiga, boreal fog |
| Mid /e/, /o/ | Temperate | Medium | Deciduous forest, savanna |
| Low-front /æ/, /ɛ/ | Hot | Low | Scrubland, desert margin |
| Low-central /a/, /ɑ/ | Hot | High | Jungle, mangrove delta |

### Syllable Structure & Phonotactics → Macrogeography

A word's syllable count controls the number of distinct terrain regions the landscape spans. A monosyllable — *krath* — generates one dramatic, unified landform: a lone massif. A polysyllable like *elaviru* generates a small archipelago or mountain chain, each syllable a distinct island of elevation, connected by the word's phonotactic rules (does the language permit consonant clusters? those become isthmus bridges).

**Stress and tone** (if the conlang uses them) control which region is elevated to the *semantic peak*: the primary-stressed syllable generates the highest-elevation zone. In a tonal conlang, a falling tone warps the density field so the landscape descends from north to south; rising tone inverts this.

---

## The Generation Pipeline

```
INPUT: conlang word in IPA transcription
         ↓
PHONEME ANALYSIS
  - extract consonant features (manner, place, voicing)
  - extract vowel features (height, backness, length, nasalization)
  - parse syllable count and stress pattern
         ↓
PARAMETER VECTOR
  - amplitude: f(consonant prominence score)
  - lacunarity: f(stop/fricative ratio)
  - octave count: f(syllable count × stress weight)
  - temperature axis: f(vowel height, inverted)
  - moisture axis: f(vowel backness + nasal consonant count)
  - erosion factor: f(liquid/fricative density)
  - geological drama: f(glottal/uvular presence)
         ↓
PERLIN NOISE SYNTHESIS
  - 2D density field: density = -y + amplitude × simplexNoise(xy, octaves)
  - lacunarity modifies how quickly detail frequency doubles per octave
         ↓
BIOME OVERLAY
  - temperature and moisture grids painted per-tile from vowel map
  - biome table lookup (Whittaker-style classification)
         ↓
WEATHER SIMULATION
  - prevailing wind direction seeded from word's reading direction
  - precipitation = moisture × elevation gradient
  - storm frequency = f(voiceless stop count)
         ↓
OUTPUT: rendered 3D landscape + named biome regions + weather report
```

---

## Concrete Examples

**Word: *velu*** (hypothetical conlang, meaning "dream-memory")
- Phonemes: /v/ (voiced labiodental fricative) + /e/ (mid-front vowel) + /l/ (lateral) + /u/ (high-back vowel)
- **/v/ + /l/** → gradual erosion, river meandering; low lacunarity
- **/e/** → temperate temperature
- **/u/** → high moisture → fog and taiga
- **Two syllables** → two connected regions; stress on first → northwestern highlands
- **Result**: A forested highland in the northwest dissolving into a foggy, river-laced lowland — an apt landscape for a dream-memory, soft and suffused.

**Word: *khrîtsk*** (harsh consonant cluster, meaning "glacier's edge")
- Phonemes: /x/ (voiceless velar fricative) + /r/ (trill) + /iː/ (long high front vowel) + /ts/ (affricate) + /k/ (voiceless velar plosive)
- **/x/, /ts/, /k/** → high lacunarity, sharp ridgelines, escarpments; maximum geological drama
- **/r/** → rough texture modifier
- **/iː/ (long)** → coldest setting; large cold zone
- **One heavy syllable** → one massive, unified landform
- **Result**: A vast glaciated massif with knife-edge arêtes, crevasse-riddled ice fields, and a single brutal caldera. The phonology is the topography.

---

## The Semantic Resonance Problem

A key design tension: should the system honor the word's *lexical meaning* (its semantics in the conlang) or rely purely on *phonological form*? The principled answer is phonology-first, for two reasons:

1. **Sound symbolism is real**. The bouba/kiki literature (Ramachandran & Hubbard, 2001; Ćwiek et al., 2022) demonstrates cross-cultural, pre-linguistic form–meaning links. A word meaning "mountain" in a language that uses voiced fricatives and low back vowels will produce rolling hills — and that *dissonance* is itself worldbuilding data. Perhaps the word predates the landscape it names, or the culture coined it in a distant homeland.

2. **Semantic input creates a second layer**. If the worldbuilder provides a gloss, the tool can run a second pass: a semantic modifier that biases the result toward the word's meaning without overriding phonological structure. A "mountain" gloss shifts amplitude upward by a multiplier; a "sea" gloss shifts moisture to maximum. Phonology sets the landscape's texture; semantics tilts the axis.

This creates **semantic dissonance art**: a word meaning "silence" in a language full of plosives generates a jagged stormland, an unsettling mismatch that deepens the world's lore.

---

## Extensions

- **Compound words and phrases** → generate multiple landscapes that can be stitched together as regional maps, phonological grammar becoming geological transition zones
- **Diachronic mode** → input a word's Proto-Language ancestor and its modern descendant; generate two landscapes and animate the tectonic drift between them as sound change
- **Export as seed** → the parameter vector is a deterministic hash of the IPA string, so any identical word always produces the same landscape, making it usable as a worldbuilding "address system" — characters name a place and the name *is* the place
- **Inverse mode** → upload a terrain heightmap; the tool infers what phonological structure would have generated it, producing a word-shaped etymology for a landscape that already exists

## Status

**Built and working.** Implemented in Python (stdlib only). Run:

```bash
uv run python toys/phonoscape/main.py --word vrakh --out scratch/vrakh.svg
uv run python toys/phonoscape/main.py --word velu --size 800
```

The tool maps phonological features to terrain parameters:
- Consonants (manner/place/voicing) → texture, drama, sharpness
- Vowels (height/backness) → temperature, moisture, biome
- Syllable count → octave count (terrain complexity)

Same word always produces the same terrain (deterministic PRNG seeded from the word).
