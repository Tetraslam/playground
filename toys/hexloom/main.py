from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

from engine import Faction, World


def load_factions() -> list[Faction]:
    factions = []
    for path in sorted((Path(__file__).parent / "factions").glob("*.py")):
        if path.name.startswith("_"):
            continue
        module = importlib.import_module(f"factions.{path.stem}")
        glyph = module.GLYPH
        color = tuple(module.COLOR)
        if len(glyph) != 1 or not glyph.isprintable():
            raise ValueError(f"{path}: GLYPH must be one printable character")
        if len(color) != 3 or not all(0 <= channel <= 255 for channel in color):
            raise ValueError(f"{path}: COLOR must contain three bytes")
        factions.append(Faction(module.NAME, glyph, color, module))
    if len({faction.name for faction in factions}) != len(factions):
        raise ValueError("faction NAME values must be unique")
    return factions


def render(world: World) -> str:
    occupied = {(organism.q, organism.r): organism for organism in world.organisms.values()}
    rows = []
    for r in range(world.height):
        row = [" " if r % 2 else ""]
        for q in range(world.width):
            organism = occupied.get((q, r))
            if organism:
                faction = world.factions[organism.faction]
                red, green, blue = faction.color
                row.append(f"\x1b[38;2;{red};{green};{blue}m{faction.glyph}\x1b[0m ")
            else:
                resource = world.resources[r * world.width + q]
                row.append("· " if resource >= 9 else ". " if resource >= 3 else "  ")
        rows.append("".join(row).rstrip())
    populations = "  ".join(
        f"{world.factions[name].glyph} {name}:{count}"
        for name, count in sorted(world.populations().items())
    )
    return f"tick {world.tick}  life {len(world.organisms)}  {populations}\n" + "\n".join(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="watch plugin factions evolve on a hex grid")
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--seed", type=int, default=6)
    parser.add_argument("--width", type=int, default=36)
    parser.add_argument("--height", type=int, default=18)
    parser.add_argument("--initial", type=int, default=12, help="organisms per faction")
    parser.add_argument("--fps", type=float, default=20.0, help="0 disables animation")
    parser.add_argument("--json", action="store_true", help="emit final summary as JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    factions = load_factions()
    world = World(
        args.width,
        args.height,
        factions,
        seed=args.seed,
        initial_per_faction=args.initial,
    )
    animate = args.fps > 0 and sys.stdout.isatty() and not args.json
    for _ in range(args.steps):
        if not world.organisms:
            break
        world.step()
        if animate:
            print("\x1b[2J\x1b[H" + render(world), end="", flush=True)
            time.sleep(1 / args.fps)

    if args.json:
        print(
            json.dumps(
                {
                    "seed": args.seed,
                    "tick": world.tick,
                    "population": dict(sorted(world.populations().items())),
                    "energy": sum(organism.energy for organism in world.organisms.values()),
                    "resources": sum(world.resources),
                },
                sort_keys=True,
            )
        )
    elif not animate:
        print(render(world))


if __name__ == "__main__":
    main()
