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


def _hash01(gx: int, gy: int, seed: int) -> float:
    """Fast integer hash -> [-1, 1]. No object allocation (was the slow path)."""
    h = (gx * 374761393 + gy * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return (h / 0xFFFFFFFF) * 2.0 - 1.0


def value_noise(x: float, y: float, rng: Rng, seed_offset: int = 0) -> float:
    """Smooth value noise, cheap integer-hashed lattice."""
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    v00 = _hash01(ix, iy, seed_offset)
    v10 = _hash01(ix + 1, iy, seed_offset)
    v01 = _hash01(ix, iy + 1, seed_offset)
    v11 = _hash01(ix + 1, iy + 1, seed_offset)

    def smooth(t: float) -> float:
        return t * t * t * (t * (t * 6 - 15) + 10)  # quintic, smoother than 3t²-2t³

    sx, sy = smooth(fx), smooth(fy)
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


def get_biome(temperature: float, moisture: float) -> tuple[str, tuple[int, int, int]]:
    """Map temperature/moisture to a biome name + its LAND base color (RGB)."""
    if temperature < 0.3:
        if moisture < 0.3:
            return "tundra", (200, 196, 178)
        elif moisture < 0.6:
            return "taiga", (74, 103, 65)
        else:
            return "boreal fog", (90, 122, 106)
    elif temperature < 0.6:
        if moisture < 0.3:
            return "scrubland", (170, 154, 104)
        elif moisture < 0.6:
            return "deciduous forest", (90, 143, 58)
        else:
            return "temperate rainforest", (61, 107, 74)
    else:
        if moisture < 0.3:
            return "desert", (216, 188, 130)
        elif moisture < 0.6:
            return "savanna", (168, 178, 100)
        else:
            return "jungle", (45, 110, 61)


# Elevation palette anchors: (threshold, RGB). The land band is tinted toward
# the biome color; water/snow are biome-independent so coastlines read clearly.
def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def elevation_color(
    h: float, sea: float, biome_rgb: tuple[int, int, int], temperature: float
) -> tuple[int, int, int]:
    """Color a normalized height with sea level, beaches, land, and peaks."""
    if h < sea * 0.55:
        return _lerp((18, 38, 74), (32, 78, 120), h / max(sea * 0.55, 1e-6))  # deep -> shelf
    if h < sea:
        return _lerp((32, 78, 120), (74, 140, 170), (h - sea * 0.55) / max(sea * 0.45, 1e-6))  # shallows
    if h < sea + 0.04:
        return (224, 208, 158)  # beach
    # land: biome color, darkening in valleys, lightening toward highlands
    land_t = (h - sea - 0.04) / max(1 - sea - 0.04, 1e-6)
    lo = _lerp((28, 44, 30), biome_rgb, 0.65)  # shadowed valley
    base = _lerp(lo, biome_rgb, min(1.0, land_t * 1.6))
    if land_t > 0.7:  # highlands -> rock
        base = _lerp(base, (122, 116, 110), (land_t - 0.7) / 0.3)
    if land_t > 0.88 and temperature < 0.55:  # snow caps in cold climates
        base = _lerp(base, (240, 244, 250), (land_t - 0.88) / 0.12)
    return base


def render(word: str, size: int) -> str:
    """Render terrain as SVG: elevation bands + biome palette + hillshade relief."""
    params = analyze_phonology(word)
    terrain = map_to_terrain(params)
    rng = Rng(word)
    biome_name, biome_rgb = get_biome(terrain["temperature"], terrain["moisture"])

    res = 140
    cell = size / res

    # Domain-warp the sample space a little so coastlines wiggle (less grid-y).
    warp = 0.35 + terrain["erosion"] * 0.4
    heightmap = [[0.0] * res for _ in range(res)]
    for y in range(res):
        for x in range(res):
            nx, ny = x / res * 4.0, y / res * 4.0
            wx = nx + warp * value_noise(nx + 11.3, ny + 4.1, rng, seed_offset=7)
            wy = ny + warp * value_noise(nx - 5.7, ny + 9.2, rng, seed_offset=19)
            h = fractal_noise(wx, wy, terrain, rng)
            h *= 1 + terrain["sharpness"]
            if terrain["drama"] > 0:
                h = math.copysign(abs(h) ** (1 - terrain["drama"] * 0.4), h)  # peaky
            heightmap[y][x] = h

    # normalize to 0..1
    flat = [h for row in heightmap for h in row]
    lo, hi = min(flat), max(flat)
    span = (hi - lo) or 1.0
    heightmap = [[(h - lo) / span for h in row] for row in heightmap]

    # sea level: wetter/colder words flood more; drama lowers it (more land/peaks)
    sea = 0.30 + terrain["moisture"] * 0.30 - terrain["drama"] * 0.12
    sea = max(0.12, min(0.62, sea))

    # light direction for hillshade (NW)
    lx, ly = -0.7, -0.7

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
    ]
    for y in range(res):
        for x in range(res):
            h = heightmap[y][x]
            r, g, b = elevation_color(h, sea, biome_rgb, terrain["temperature"])
            # hillshade: slope from neighbors (only on land, where it reads)
            if h >= sea:
                hx = heightmap[y][min(x + 1, res - 1)] - heightmap[y][max(x - 1, 0)]
                hy = heightmap[min(y + 1, res - 1)][x] - heightmap[max(y - 1, 0)][x]
                shade = 1.0 + (hx * lx + hy * ly) * 3.2
                shade = max(0.6, min(1.35, shade))
                r = max(0, min(255, int(r * shade)))
                g = max(0, min(255, int(g * shade)))
                b = max(0, min(255, int(b * shade)))
            parts.append(
                f'<rect x="{x * cell:.2f}" y="{y * cell:.2f}" width="{cell:.2f}" '
                f'height="{cell:.2f}" fill="#{r:02x}{g:02x}{b:02x}"/>'
            )

    # a couple of crisp coastline strokes for legibility
    parts.append('<g fill="none" stroke="rgba(20,30,40,0.35)" stroke-width="0.8">')
    for y in range(1, res):
        for x in range(1, res):
            a = heightmap[y][x] >= sea
            if a != (heightmap[y][x - 1] >= sea) or a != (heightmap[y - 1][x] >= sea):
                parts.append(
                    f'<rect x="{x * cell:.2f}" y="{y * cell:.2f}" '
                    f'width="{cell:.2f}" height="{cell:.2f}"/>'
                )
    parts.append("</g></svg>")
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