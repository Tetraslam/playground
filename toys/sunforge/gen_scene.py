"""sunforge stage 1: simulate everything, emit plain data for Blender.

Usage:
    uv run python toys/sunforge/gen_scene.py --seed 7 [--frequency 48]

Writes renders/data/: lattice.npz, ca.npz, statemap_####.png (+ previews).
Later milestones add path.json (M4), drones.npz + events.json (M5).
See DESIGN.md §5 for the contract.
"""

import argparse
import time
from pathlib import Path

import numpy as np
from sim import N_FRAMES
from sim.construction import LIVE, TRUSS, run_ca, state_at
from sim.flightpath import build_corridor
from sim.lattice import build_lattice
from sim.statemaps import render_statemaps

DATA_DIR = Path(__file__).parent / "renders" / "data"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--frequency", type=int, default=48, help="icosphere subdivision frequency")
    ap.add_argument("--statemap-every", type=int, default=24, help="film frames per statemap")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    lattice = build_lattice(args.frequency)
    np.savez_compressed(DATA_DIR / "lattice.npz", **lattice)
    n = len(lattice["centers"])
    print(f"[lattice] {n} cells ({len(lattice['pentagons'])} foundries)")

    ca = run_ca(lattice, seed=args.seed)
    np.savez_compressed(DATA_DIR / "ca.npz", **ca)
    for f in (1, N_FRAMES):
        s = state_at(ca, f)
        print(
            f"[ca] frame {f}: built {np.mean(s >= TRUSS):.1%}"
            f"  live {np.mean(s == LIVE):.1%}  void {np.mean(s == 0):.1%}"
        )

    corridor = build_corridor(lattice)
    np.savez_compressed(DATA_DIR / "corridor.npz", **corridor)
    print(f"[corridor] {len(corridor['ids'])} cells under the provisional arc")

    paths = render_statemaps(lattice, ca, DATA_DIR, seed=args.seed, every=args.statemap_every)
    print(f"[statemaps] {len(paths)} maps + previews -> {DATA_DIR}")
    print(f"[done] seed={args.seed} in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
