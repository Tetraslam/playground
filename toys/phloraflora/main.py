"""phloraflora — grow a conlang word into an L-system plant, rendered as SVG.

Every phoneme is a biological instruction. A word's sounds drive an L-system's
branching angle, segment length, recursion depth, stochastic variance, and
palette — so the plant *feels* native to the word's phonaesthetics. Type a word;
watch it grow. Same word -> same plant (deterministic).

    uv run python toys/phloraflora/main.py --word veltharion --out scratch/vel.svg
    uv run python toys/phloraflora/main.py --word gox --depth 5

Idea seeded by a `lain` exploration ("Phoneme-to-Flora"). Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import re

# --- phoneme feature classes (rough, letter-based approximation of IPA) -------
# We map orthography -> articulatory class. Good enough for conlang romanizations.
NASALS = set("mnŋ")
LATERALS = set("lrwjy")  # laterals + approximants (fluid)
STOPS = set("ptkbdgq")
FRICATIVES = set("szfvþ")  # incl. some common conlang glyphs
VELARS = set("kgq")
LABIALS = set("pbmfv")
VOICED = set("bdgvzmnlrwjy")
VOWELS = set("aeiouáéíóúäëïöü")
FRONT_VOWELS = set("ieéí")
BACK_VOWELS = set("aouáóú")


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


def analyze(word: str) -> dict:
    """Turn a word's phonemes into L-system parameters."""
    w = re.sub(r"[^a-zþäëïöüáéíóú]", "", word.lower())
    if not w:
        w = "aa"
    n = len(w)

    def frac(s: set[str]) -> float:
        return sum(c in s for c in w) / n

    nas, lat, stp, fri = frac(NASALS), frac(LATERALS), frac(STOPS), frac(FRICATIVES)
    vel, voi = frac(VELARS), frac(VOICED)
    front, back = frac(FRONT_VOWELS), frac(BACK_VOWELS)

    # Branching angle: nasals narrow it (columnar), stops widen it (bushy).
    angle = 18 + stp * 34 - nas * 10  # degrees
    # Segment length ratio: laterals elongate, velars shorten/compact.
    seg_ratio = 0.72 + lat * 0.18 - vel * 0.15
    # Recursion depth: voiced consonants add complexity.
    depth = 4 + round(voi * 3)
    # Stochastic variance: fricatives add wind-shaped asymmetry.
    variance = fri * 0.5
    # Hue: front vowels -> luminous greens/cyans; back vowels -> dark olive/amber.
    hue = int(90 + front * 90 - back * 70) % 360
    # Saturation/lightness: back vowels darker & rougher.
    light = max(28, min(70, int(60 - back * 22 + front * 8)))

    return {
        "word": w,
        "angle": max(8, min(60, angle)),
        "seg_ratio": max(0.5, min(0.95, seg_ratio)),
        "depth": max(3, min(7, depth)),
        "variance": variance,
        "hue": hue,
        "light": light,
    }


def lsystem(params: dict, rng: Rng) -> str:
    """Expand a simple stochastic bracketed L-system into a turtle string."""
    # F = draw forward, +/- = turn, [ ] = push/pop. Branch rule varies by params.
    axiom = "F"
    # More variance -> more chance of asymmetric rules.
    rules_pool = [
        "F[+F]F[-F]F",
        "F[+F]F[-F][F]",
        "FF[+F][-F]F",
        "F[-F][+F]",
    ]
    s = axiom
    for _ in range(params["depth"]):
        out = []
        for ch in s:
            if ch == "F":
                idx = int(rng.rand() * len(rules_pool)) if params["variance"] > 0.15 else 0
                out.append(rules_pool[idx])
            else:
                out.append(ch)
        s = "".join(out)
        if len(s) > 60000:  # safety cap
            break
    return s


def render(word: str, size: int) -> str:
    params = analyze(word)
    rng = Rng(word)
    s = lsystem(params, rng)

    angle = params["angle"]
    seg = size * 0.045 * params["seg_ratio"]
    variance = params["variance"]
    hue = params["hue"]
    light = params["light"]

    # turtle state
    x, y = size / 2, size * 0.96
    heading = -90.0  # pointing up
    stack: list[tuple[float, float, float, float]] = []
    seg_len = seg
    segments: list[tuple[float, float, float, float, float]] = []  # x1,y1,x2,y2,depth_frac

    depth_now = 0
    max_depth_seen = 1
    for ch in s:
        if ch == "F":
            jitter = (rng.rand() - 0.5) * variance * 18
            rad = math.radians(heading + jitter)
            nx = x + seg_len * math.cos(rad)
            ny = y + seg_len * math.sin(rad)
            segments.append((x, y, nx, ny, depth_now))
            x, y = nx, ny
        elif ch == "+":
            heading += angle + (rng.rand() - 0.5) * variance * 12
        elif ch == "-":
            heading -= angle + (rng.rand() - 0.5) * variance * 12
        elif ch == "[":
            stack.append((x, y, heading, seg_len))
            depth_now += 1
            max_depth_seen = max(max_depth_seen, depth_now)
            seg_len *= params["seg_ratio"]
        elif ch == "]":
            x, y, heading, seg_len = stack.pop()
            depth_now -= 1

    # render: thicker/darker trunk near base, thinner/lighter luminous tips
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">',
        f'<rect width="{size}" height="{size}" fill="hsl({hue}, 28%, 7%)"/>',
    ]
    for x1, y1, x2, y2, d in segments:
        t = d / max_depth_seen  # 0 = trunk, 1 = tip
        width = max(0.6, (1 - t) * size * 0.012)
        light_t = min(85, light + t * 28)
        sat = 45 + t * 25
        color = f"hsl({(hue + int(t * 25)) % 360}, {sat:.0f}%, {light_t:.0f}%)"
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="{width:.1f}" stroke-linecap="round"/>'
        )
    # luminous buds at the tips (terminal segments)
    for x1, y1, x2, y2, d in segments:
        if d >= max_depth_seen - 1 and rng.rand() > 0.6:
            r = 1.5 + rng.rand() * 2.5
            parts.append(
                f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="{r:.1f}" '
                f'fill="hsl({(hue + 40) % 360}, 80%, 75%)" opacity="0.85"/>'
            )
    parts.append("</svg>")
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Grow a conlang word into an L-system plant.")
    ap.add_argument("--word", default="veltharion", help="seed word")
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
    p = analyze(args.word)
    print(
        f'phloraflora: grew "{p["word"]}" -> {args.out}  '
        f'(angle {p["angle"]:.0f}°, depth {p["depth"]}, hue {p["hue"]})'
    )


if __name__ == "__main__":
    main()
