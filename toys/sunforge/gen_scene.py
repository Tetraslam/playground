"""sunforge stage 1: simulate everything, emit plain data for Blender.

Usage:
    uv run python toys/sunforge/gen_scene.py --seed 7 [--frequency 48]

Writes renders/data/ (lattice.npz, states.npz, statemap_####.png,
drones.npz, path.json, events.json). See DESIGN.md §5 for the contract.
"""

import argparse
from pathlib import Path

DATA_DIR = Path(__file__).parent / "renders" / "data"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--frequency", type=int, default=48, help="icosphere subdivision frequency")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # M1: lattice + CA + statemaps. M4: path. M5: swarm + events.
    raise NotImplementedError(f"M1 starts here (seed={args.seed})")


if __name__ == "__main__":
    main()
