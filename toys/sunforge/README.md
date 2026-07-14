# sunforge

A Dyson shell under construction, watched for two minutes from a freighter
window. A construction CA on a ~40k-cell Goldberg lattice, job-driven drone
swarms, and an event timeline all feed one continuous 120s shot: dark-side
city lights → the live construction front → the blazing gap → a mass-driver
launch → docking. Everything on screen is simulation output.

**Status: designed, not yet built.** The full plan (shot table, systems,
scale cheat, render budget, milestones) is in [DESIGN.md](./DESIGN.md).

## Run (target shape — lands with M1+)

```bash
# 1. simulate (uv side): lattice, CA, drones, path, events -> renders/data/
uv run python toys/sunforge/gen_scene.py --seed 7

# 2. build (blender side): data -> renders/shell.blend
tools/blender.sh run toys/sunforge/build_scene.py

# 3. render the film (one blender process, resumable chunks)
tools/blender.sh run toys/sunforge/render_anim.py -- --start 1 --end 2880

# 4. look before you leap (always)
tools/blender.sh snap toys/sunforge/renders/shell.blend toys/sunforge/renders/snap.png
```

Deterministic: one `--seed` drives the lattice, the CA, the boids, the shake,
and the greebles. Same seed, same film.

_Built by fable._
