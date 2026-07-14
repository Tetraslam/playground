# sunforge

A Dyson shell under construction, watched for two minutes from a freighter
window. A construction CA on a ~40k-cell Goldberg lattice, job-driven drone
swarms, and an event timeline all feed one continuous 120s shot: dark-side
city lights → the live construction front → the blazing gap → a mass-driver
launch → docking. Everything on screen is simulation output.

The full plan (shot table, systems, scale cheat, render budget, milestones)
is in [DESIGN.md](./DESIGN.md).

**Status: M2 done** — the far layer lives in Blender. `build_scene.py` builds
the whole-shell sphere whose shader decodes the statemaps (state → alpha +
ember/city/commissioning emission with sub-cell "street" texture), the star
and its light (the interior is lit physically — the terminator and the
aperture blaze are free), a voronoi starfield, bloom via the 5.x group
compositor, and a hero camera staged *against the CA state* (it finds the
construction frontier by walking the equator arc — never eyeballed).

![establishing shot](examples/m2_establishing.png)

![the frontier from 350 up](examples/m2_hero_frontier.png)

**M1** — the sim runs headless. Goldberg lattice (23042 cells,
12 pentagon foundries), first-passage construction CA staged so a finished
city-lit hemisphere opposes the great unbuilt aperture, equirect statemaps +
previews every 24 frames. `gen_scene.py --seed 7` reproduces everything in
~15s.

![construction CA over the film](examples/m1_ca_strip.png)

The front, close up, at film start vs film end (hex cells popping VOID→TRUSS,
ripening to plate, new city lights igniting):

![front advance](examples/m1_front_advance.png)

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
