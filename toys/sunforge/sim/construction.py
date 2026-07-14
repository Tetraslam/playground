"""Construction cellular automaton on the shell lattice (DESIGN.md §2.2).

Per-cell state machine VOID -> TRUSS -> PLATE -> LIVE, spreading along
adjacency from the 12 pentagon foundries. Edge noise for ragged fronts,
build rate coupled to drone throughput (sim.swarm), scripted stalls/bursts
from events.json. Runs N_FRAMES ticks, one per film frame.

Outputs:
  renders/data/statemap_####.png   equirect far-field emission maps (every 24f)
  renders/data/states.npz          corridor-only (cell, frame, new_state) events
"""

VOID, TRUSS, PLATE, LIVE = 0, 1, 2, 3

# M1. Not yet implemented.


def run_ca(lattice, seed: int, n_frames: int):
    raise NotImplementedError("M1: front propagation + state history")
