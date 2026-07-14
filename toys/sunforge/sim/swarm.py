"""Builder-drone boids with jobs (DESIGN.md §2.3).

Separation/alignment/cohesion + goal-seek; jobs cycle foundry -> active
front cell -> foundry. Throughput feeds back into the CA build rate, so
the visible swarm is *why* the front advances. ~300 near-corridor drones
baked per-frame; distant swarms become cheap particles Blender-side.

Output: renders/data/drones.npz  positions/headings (n_drones, N_FRAMES, 3+3)
"""

# M5 (sim core lands with M1's data shapes). Not yet implemented.


def run_swarm(lattice, ca_history, path, seed: int):
    raise NotImplementedError("M5: boids + job assignment")
