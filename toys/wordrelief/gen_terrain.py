"""gen_terrain.py — stage 1 of wordrelief (runs under uv, NOT blender).

Borrows phonoscape's phonology->terrain math (imported by path — it's
stdlib-only) and emits a plain JSON heightmap + vertex colors that
build_scene.py consumes inside Blender.

Run:  uv run python toys/wordrelief/gen_terrain.py --word vrakh
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# phonoscape is stdlib-only, so importing it by path is safe and keeps the
# terrain math in one place (the compose-over-copy rule).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phonoscape"))
from main import (  # noqa: E402
    Rng,
    analyze_phonology,
    elevation_color,
    fractal_noise,
    get_biome,
    map_to_terrain,
    value_noise,
)


def generate(word: str, res: int) -> dict:
    params = analyze_phonology(word)
    terrain = map_to_terrain(params)
    rng = Rng(word)
    biome_name, biome_rgb = get_biome(terrain["temperature"], terrain["moisture"])

    # Same heightmap loop as phonoscape's SVG renderer (domain-warped fBm).
    warp = 0.35 + terrain["erosion"] * 0.4
    heights = [0.0] * (res * res)
    for y in range(res):
        for x in range(res):
            nx, ny = x / res * 4.0, y / res * 4.0
            wx = nx + warp * value_noise(nx + 11.3, ny + 4.1, rng, seed_offset=7)
            wy = ny + warp * value_noise(nx - 5.7, ny + 9.2, rng, seed_offset=19)
            h = fractal_noise(wx, wy, terrain, rng)
            h *= 1 + terrain["sharpness"]
            if terrain["drama"] > 0:
                h = math.copysign(abs(h) ** (1 - terrain["drama"] * 0.4), h)
            heights[y * res + x] = h

    lo, hi = min(heights), max(heights)
    span = (hi - lo) or 1.0
    heights = [(h - lo) / span for h in heights]

    sea = 0.30 + terrain["moisture"] * 0.30 - terrain["drama"] * 0.12
    sea = max(0.12, min(0.62, sea))

    colors = [
        elevation_color(h, sea, biome_rgb, terrain["temperature"]) for h in heights
    ]

    return {
        "word": word,
        "res": res,
        "sea": sea,
        "biome": biome_name,
        "terrain": terrain,
        "heights": heights,
        "colors": colors,  # sRGB 0-255 triples, row-major like heights
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="conlang word -> terrain JSON for build_scene.py")
    ap.add_argument("--word", default="vrakh")
    ap.add_argument("--res", type=int, default=140, help="grid resolution per side")
    ap.add_argument("--out", default="", help="output JSON (default: renders/<word>.json)")
    args = ap.parse_args()

    out = Path(args.out) if args.out else Path(__file__).parent / "renders" / f"{args.word}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = generate(args.word, args.res)
    out.write_text(json.dumps(data))
    print(f"{args.word}: biome={data['biome']} sea={data['sea']:.2f} -> {out}")


if __name__ == "__main__":
    main()
