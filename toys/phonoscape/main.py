"""phonoscape — turn a conlang word into a procedural terrain SVG.

Phonological features map to terrain parameters: place/manner/voicing of consonants
control texture and drama, while vowel height/backness determine climate and biome.
Same word -> same terrain (deterministic).

    uv run python toys/phonoscape/main.py --word vrakh --out scratch/vrakh.svg
    uv run python toys/phonoscape/main.py --word velu --size 800

Idea seeded by a `lain` exploration (root-3). Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import re

# --- phoneme feature sets (letter-based approximation of IPA) --------------
# Consonants by manner
VOICELESS_PLOSIVES = set("ptkq")
VOICED_PLOSIVES = set("bdg")
FRICATIVES = set("szfvxh")  # x = velar fricative, h = glottal
VOICED_FRICATIVES = set("vzð")
SIBILANTS = set("sʃz")
NASALS = set("mnŋ")
LIQUIDS = set("lr")
LATERALS = set("l")
GLIDE_APPROXIMANTS = set("wjy")

# Consonants by place
BILABIALS = set("pbm")
LABIODENTALS = set("fv")
DENTALS = set("tdnzs")
ALVEOLARS = set("tdnszlr")
VELARS = set("kgŋx")
UVULARS = set("qɣʁ")
GLOTTALS = set("h")

# Voicing
VOICED = set("bdgvzmnŋlrwjyðɣʁ")

# Vowels by height
HIGH_VOWELS = set("iɪuʊ")
MID_VOWELS = set("eəoɔ")
LOW_VOWELS = set("aæɑɛ")

# Vowels by backness
FRONT_VOWELS = set("iɪeæɛ")
CENTRAL_VOWELS = set("aəɑ")
BACK_VOWELS = set("uʊoɔ")

# All vowels (for detection)
VOWELS = set("aeiouyáéíóúäëïöüæɑəɛɪʊɔ")

# Long vowel markers (diacritics)
LONG_MARKERS = set("āēīōūæǣǽ")


class Rng:
    """Deterministic splitmix64-ish PRNG seeded from the word."""

    def __init__(self, seed: str):
        self.s = int.from_bytes(hashlib.blake2b(seed.encode(), digest_size=8).digest(), "little")

    def _next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def rand(self) -> float:
        return (self._next() >> 11) / float(1 << 53)


def analyze_phonology(word: str) -> dict:
    """Extract phonological features from a word."""
    # Normalize: keep only letters we can classify
    w = re.sub(r"[^a-zæɑəɛɪʊɔáéíóúäëïöü]", "", word.lower())
    if not w:
        w = "aa"

    n = len(w)

    def frac(s: set[str]) -> float:
        return sum(c in s for c in w) / n

    # Consonant features
    voiceless_plosive_frac = frac(VOICELESS_PLOSIVES)
    voiced_plosive_frac = frac(VOICED_PLOSIVES)
    fricative_frac = frac(FRICATIVES)
    sibilant_frac = frac(SIBILANTS)
    nasal_frac = frac(NASALS)
    liquid_frac = frac(LIQUIDS)
    glottal_uvular_frac = frac(GLOTTALS | UVULARS)
    voiced_frac = frac(VOICED)

    # Place of articulation
    bilabial_frac = frac(BILABIALS)
    velar_uvular_frac = frac(VELARS | UVULARS)

    # Vowel features
    vowel_chars = [c for c in w if c in VOWELS]
    n_vowels = len(vowel_chars) or 1

    def vowel_frac(s: set[str]) -> float:
        return sum(c in s for c in vowel_chars) / n_vowels

    high_vowel_frac = vowel_frac(HIGH_VOWELS)
    mid_vowel_frac = vowel_frac(MID_VOWELS)
    low_vowel_frac = vowel_frac(LOW_VOWELS)
    front_vowel_frac = vowel_frac(FRONT_VOWELS)
    back_vowel_frac = vowel_frac(BACK_VOWELS)

    # Syllable count (approximate: vowel count)
    syllable_count = n_vowels

    # Stress (simple heuristic: first vowel gets primary stress)
    stress_pos = 0  # first syllable stressed

    return {
        "word": w,
        "voiceless_plosive_frac": voiceless_plosive_frac,
        "voiced_plosive_frac": voiced_plosive_frac,
        "fricative_frac": fricative_frac,
        "sibilant_frac": sibilant_frac,
        "nasal_frac": nasal_frac,
        "liquid_frac": liquid_frac,
        "glottal_uvular_frac": glottal_uvular_frac,
        "voiced_frac": voiced_frac,
        "bilabial_frac": bilabial_frac,
        "velar_uvular_frac": velar_uvular_frac,
        "high_vowel_frac": high_vowel_frac,
        "mid_vowel_frac": mid_vowel_frac,
        "low_vowel_frac": low_vowel_frac,
        "front_vowel_frac": front_vowel_frac,
        "back_vowel_frac": back_vowel_frac,
        "syllable_count": syllable_count,
        "stress_pos": stress_pos,
    }


def map_to_terrain(params: dict) -> dict:
    """Map phonological features to terrain generation parameters."""
    # Amplitude: consonant prominence (plosives increase drama)
    amplitude = 0.3 + params["voiceless_plosive_frac"] * 0.4 + params["voiced_plosive_frac"] * 0.2

    # Lacunarity: stop/fricative ratio (plosives = high lacunarity = sharp detail)
    lacunarity = 1.8 + params["voiceless_plosive_frac"] * 1.5 - params["nasal_frac"] * 0.5

    # Octave count: syllable count × stress weight
    octaves = 3 + min(3, params["syllable_count"])

    # Temperature axis: vowel height (inverted: high vowels = cold)
    temperature = 1.0 - params["high_vowel_frac"] * 0.7 + params["low_vowel_frac"] * 0.5

    # Moisture axis: vowel backness + nasal consonant count
    moisture = params["back_vowel_frac"] * 0.6 + params["nasal_frac"] * 0.4

    # Erosion factor: liquid/fricative density
    erosion = params["liquid_frac"] * 0.5 + params["voiced_frac"] * 0.3

    # Geological drama: glottal/uvular presence
    drama = params["glottal_uvular_frac"] * 0.8

    # Ridge sharpness: velar/uvular vs bilabial
    sharpness = params["velar_uvular_frac"] * 0.7 - params["bilabial_frac"] * 0.3

    return {
        "amplitude": amplitude,
        "lacunarity": max(1.2, min(3.5, lacunarity)),
        "octaves": octaves,
        "temperature": max(0.1, min(1.0, temperature)),
        "moisture": max(0.0, min(1.0, moisture)),
        "erosion": max(0.0, min(1.0, erosion)),
        "drama": max(0.0, min(1.0, drama)),
        "sharpness": max(-0.5, min(0.5, sharpness)),
    }


def value_noise(x: float, y: float, rng: Rng, seed_offset: int = 0) -> float:
    """Simple value noise for terrain generation."""
    # Integer grid coordinates
    ix, iy = int(x), int(y)
    # Local coordinates
    fx, fy = x - ix, y - iy

    # Hash function for grid points
    def hash_grid(gx: int, gy: int) -> float:
        h = (gx * 374761393 + gy * 668265263 + seed_offset) & 0xFFFFFFFF
        h = (h ^ (h >> 13)) * 1274126177
        h = (h ^ (h >> 16))
        # Use this to seed a deterministic value
        rng_local = Rng(f"noise_{h}")
        return rng_local.rand() * 2 - 1

    # Corner values
    v00 = hash_grid(ix, iy)
    v10 = hash_grid(ix + 1, iy)
    v01 = hash_grid(ix, iy + 1)
    v11 = hash_grid(ix + 1, iy + 1)

    # Smooth interpolation
    def smooth(t: float) -> float:
        return t * t * (3 - 2 * t)

    sx = smooth(fx)
    sy = smooth(fy)

    # Bilinear interpolation
    nx0 = v00 + sx * (v10 - v00)
    nx1 = v01 + sx * (v11 - v01)
    return nx0 + sy * (nx1 - nx0)


def fractal_noise(
    x: float, y: float, terrain: dict, rng: Rng, seed_offset: int = 0
) -> float:
    """Fractal noise with octave layering."""
    amplitude = terrain["amplitude"]
    lacunarity = terrain["lacunarity"]
    octaves = terrain["octaves"]

    value = 0.0
    max_value = 0.0
    freq = 1.0
    amp = amplitude

    for _ in range(octaves):
        value += value_noise(x * freq, y * freq, rng, seed_offset) * amp
        max_value += amp
        freq *= lacunarity
        amp *= 0.5

    return value / max_value if max_value > 0 else 0.0


def get_biome(temperature: float, moisture: float) -> tuple[str, str]:
    """Map temperature/moisture to biome name and color."""
    # Whittaker-style biome classification
    if temperature < 0.3:
        if moisture < 0.3:
            return "tundra", "#e8dcc8"
        elif moisture < 0.6:
            return "taiga", "#4a6741"
        else:
            return "boreal fog", "#5a7a6a"
    elif temperature < 0.6:
        if moisture < 0.3:
            return "scrubland", "#c9b896"
        elif moisture < 0.6:
            return "deciduous forest", "#5a8f3a"
        else:
            return "temperate rainforest", "#3d6b4a"
    else:
        if moisture < 0.3:
            return "desert", "#e6d5a8"
        elif moisture < 0.6:
            return "savanna", "#a8c686"
        else:
            return "jungle", "#2d5a3d"


def render(word: str, size: int) -> str:
    """Render terrain as SVG."""
    params = analyze_phonology(word)
    terrain = map_to_terrain(params)
    rng = Rng(word)

    # Grid resolution
    resolution = 100
    cell_size = size / resolution

    # Generate heightmap
    heightmap = []
    for y in range(resolution):
        row = []
        for x in range(resolution):
            # Normalize coordinates
            nx = x / resolution * 4
            ny = y / resolution * 4

            # Base fractal noise
            h = fractal_noise(nx, ny, terrain, rng)

            # Apply erosion smoothing
            if terrain["erosion"] > 0.3:
                # Simple smoothing pass
                h = h * (1 - terrain["erosion"] * 0.3)

            # Apply sharpness
            h = h * (1 + terrain["sharpness"])

            # Apply drama (more extreme values)
            if terrain["drama"] > 0:
                h = h * (1 + terrain["drama"])

            row.append(h)
        heightmap.append(row)

    # Normalize heightmap to 0-1
    min_h = min(min(row) for row in heightmap)
    max_h = max(max(row) for row in heightmap)
    if max_h > min_h:
        heightmap = [[(h - min_h) / (max_h - min_h) for h in row] for row in heightmap]

    # Generate SVG
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">',
    ]

    # Render cells with biome coloring
    for y in range(resolution):
        for x in range(resolution):
            h = heightmap[y][x]
            biome_name, biome_color = get_biome(terrain["temperature"], terrain["moisture"])

            # Adjust color by elevation
            # Higher = lighter/more saturated, lower = darker
            elevation_factor = h * 0.4 - 0.2

            # Parse hex color and adjust
            r = int(biome_color[1:3], 16)
            g = int(biome_color[3:5], 16)
            b = int(biome_color[5:7], 16)

            # Apply elevation adjustment
            r = max(0, min(255, int(r * (1 + elevation_factor))))
            g = max(0, min(255, int(g * (1 + elevation_factor))))
            b = max(0, min(255, int(b * (1 + elevation_factor))))

            color = f"#{r:02x}{g:02x}{b:02x}"

            px = x * cell_size
            py = y * cell_size
            parts.append(
                f'<rect x="{px:.1f}" y="{py:.1f}" width="{cell_size:.1f}" height="{cell_size:.1f}" '
                f'fill="{color}" stroke="none"/>'
            )

    # Add contour lines for elevation
    parts.append('<g stroke="rgba(0,0,0,0.15)" stroke-width="0.5" fill="none">')
    for y in range(resolution):
        for x in range(resolution):
            h = heightmap[y][x]
            if h > 0.7 and h < 0.75:  # High elevation contour
                px = x * cell_size
                py = y * cell_size
                parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{cell_size * 0.4}"/>')
            elif h > 0.3 and h < 0.35:  # Mid elevation contour
                px = x * cell_size
                py = y * cell_size
                parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{cell_size * 0.3}"/>')
    parts.append('</g>')

    parts.append("</svg>")
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Turn a conlang word into a procedural terrain SVG.")
    ap.add_argument("--word", default="vrakh", help="seed word")
    ap.add_argument("--out", default="", help="output SVG path (default: stdout)")
    ap.add_argument("--size", type=int, default=500, help="canvas size px")
    args = ap.parse_args()

    svg = render(args.word, args.size)
    if not args.out:
        print(svg)
        return

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)

    params = analyze_phonology(args.word)
    terrain = map_to_terrain(params)
    biome_name, _ = get_biome(terrain["temperature"], terrain["moisture"])

    print(
        f'phonoscape: rendered "{params["word"]}" -> {args.out}  '
        f'(biome: {biome_name}, amplitude: {terrain["amplitude"]:.2f}, '
        f'octaves: {terrain["octaves"]})'
    )


if __name__ == "__main__":
    main()