"""Goldberg-polyhedron shell lattice (DESIGN.md §2.1).

Subdivide an icosahedron (frequency ~48-64), take the dual: ~23k-41k hex
cells + exactly 12 pentagons (the foundry sites). Per cell: center (unit
sphere), tangent frame, area, adjacency list.

Output: renders/data/lattice.npz
  centers   (N, 3) float32   unit vectors
  frames    (N, 3, 3) float32  per-cell tangent basis
  areas     (N,) float32
  neighbors (N, 6) int32     -1-padded (pentagons have 5)
  pentagons (12,) int32      cell indices of the foundries
"""

# M1. Not yet implemented.


def build_lattice(frequency: int, seed: int):
    raise NotImplementedError("M1: icosphere subdivision + dual")
