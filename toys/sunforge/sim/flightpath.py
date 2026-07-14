"""Flight corridor + cell polygons (DESIGN.md §2.5, §3).

M3 scope: a *provisional* corridor — the band of cells the camera will fly
over — plus exact dual-cell polygons for the near-layer geometry. Each
Goldberg cell's corners are the (projected) barycenters of consecutive
neighbor triples; corners are shared between adjacent cells, so the
near-layer tiles seamlessly. M4 replaces the provisional arc with the real
spline path (same corridor contract).

Output (renders/data/corridor.npz):
  ids      (K,)   int32    corridor cell indices into the lattice
  offsets  (K+1,) int64    corners[offsets[i]:offsets[i+1]] belong to ids[i]
  corners  (M, 3) float32  unit vectors, CCW around each cell (seen from
                            outside), starting at an arbitrary corner
"""

from __future__ import annotations

import numpy as np

GAP_AXIS = np.array([1.0, 0.0, 0.0])


def sorted_neighbors(lattice: dict[str, np.ndarray], cell: int) -> np.ndarray:
    """Cell's neighbors, CCW-sorted around its center (seen from outside)."""
    c = lattice["centers"][cell].astype(np.float64)
    t1, t2 = lattice["frames"][cell][0], lattice["frames"][cell][1]
    nbrs = lattice["neighbors"][cell]
    nbrs = nbrs[nbrs >= 0]
    rel = lattice["centers"][nbrs].astype(np.float64) - c
    ang = np.arctan2(rel @ t2, rel @ t1)
    return nbrs[np.argsort(ang)]


def cell_polygons(lattice: dict[str, np.ndarray], ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Exact dual polygons: corner k = normalize(c + n_k + n_{k+1})."""
    centers = lattice["centers"].astype(np.float64)
    offsets = [0]
    corners: list[np.ndarray] = []
    for cell in ids:
        nbrs = sorted_neighbors(lattice, int(cell))
        c = centers[cell]
        for k in range(len(nbrs)):
            tri = c + centers[nbrs[k]] + centers[nbrs[(k + 1) % len(nbrs)]]
            corners.append(tri / np.linalg.norm(tri))
        offsets.append(len(corners))
    return np.asarray(corners, dtype=np.float32), np.asarray(offsets, dtype=np.int64)


def provisional_corridor(
    lattice: dict[str, np.ndarray],
    half_width: float = 0.05,
    theta_range: tuple[float, float] = (45.0, 180.0),
) -> np.ndarray:
    """Cells under the provisional flight arc: the +Y equator great circle.

    half_width is |z|/R (0.05 ≈ 2.9° ≈ 100 units at R=2000); theta_range is
    the polar-angle span from the gap axis (+X) that the film crosses.
    """
    centers = lattice["centers"].astype(np.float64)
    theta = np.degrees(np.arccos(np.clip(centers @ GAP_AXIS, -1.0, 1.0)))
    in_band = np.abs(centers[:, 2]) < half_width
    on_side = centers[:, 1] > 0.0
    in_span = (theta_range[0] <= theta) & (theta <= theta_range[1])
    return np.flatnonzero(in_band & on_side & in_span).astype(np.int32)


def build_corridor(lattice: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    ids = provisional_corridor(lattice)
    corners, offsets = cell_polygons(lattice, ids)
    return {"ids": ids, "offsets": offsets, "corners": corners}
