"""Goldberg-polyhedron shell lattice (DESIGN.md §2.1).

Subdivide an icosahedron at integer frequency f and identify each subdivided
*vertex* with a Goldberg cell (the dual): 10f²+2 cells, of which exactly 12
are pentagons (the original icosahedron vertices — our foundry sites).
Everything is numpy; adjacency comes from the subdivided triangulation.

Contract (renders/data/lattice.npz):
  centers   (N, 3) float32     unit vectors
  frames    (N, 3, 3) float32  rows = [tangent1, tangent2, normal]
  areas     (N,) float32       steradians (sums to ~4π)
  neighbors (N, 6) int32       -1-padded (pentagons have 5)
  pentagons (12,) int32        foundry cell indices
"""

from __future__ import annotations

import numpy as np


def icosahedron() -> tuple[np.ndarray, np.ndarray]:
    """Unit icosahedron: (12,3) float64 verts, (20,3) int faces (CCW outward)."""
    p = (1.0 + np.sqrt(5.0)) / 2.0
    verts = np.array(
        [
            (-1, p, 0),
            (1, p, 0),
            (-1, -p, 0),
            (1, -p, 0),
            (0, -1, p),
            (0, 1, p),
            (0, -1, -p),
            (0, 1, -p),
            (p, 0, -1),
            (p, 0, 1),
            (-p, 0, -1),
            (-p, 0, 1),
        ],
        dtype=np.float64,
    )
    verts /= np.linalg.norm(verts, axis=1, keepdims=True)
    faces = np.array(
        [
            (0, 11, 5),
            (0, 5, 1),
            (0, 1, 7),
            (0, 7, 10),
            (0, 10, 11),
            (1, 5, 9),
            (5, 11, 4),
            (11, 10, 2),
            (10, 7, 6),
            (7, 1, 8),
            (3, 9, 4),
            (3, 4, 2),
            (3, 2, 6),
            (3, 6, 8),
            (3, 8, 9),
            (4, 9, 5),
            (2, 4, 11),
            (6, 2, 10),
            (8, 6, 7),
            (9, 8, 1),
        ],
        dtype=np.int64,
    )
    return verts, faces


def _subdivide(verts: np.ndarray, faces: np.ndarray, f: int) -> tuple[np.ndarray, np.ndarray]:
    """Subdivide each face into f² triangles; return (points, tris), deduped.

    Points are unit-normalized. Dedupe is by rounding to 1e-6 (grid spacing at
    f=64 is ~0.017, so this is safe by ~4 orders of magnitude); the caller
    asserts the exact expected count 10f²+2.
    """
    pts: list[np.ndarray] = []
    tris: list[tuple[int, int, int]] = []
    offset = 0
    # local grid index for barycentric (i, j): row-major over i (0..f), j (0..f-i)
    for v0, v1, v2 in verts[faces]:
        idx = {}
        k = 0
        for i in range(f + 1):
            for j in range(f + 1 - i):
                idx[(i, j)] = offset + k
                k += 1
                pts.append((v0 * (f - i - j) + v1 * i + v2 * j) / f)
        for i in range(f):
            for j in range(f - i):
                a, b, c = idx[(i, j)], idx[(i + 1, j)], idx[(i, j + 1)]
                tris.append((a, b, c))
                if i + j < f - 1:
                    d = idx[(i + 1, j + 1)]
                    tris.append((b, d, c))
        offset += k
    points = np.asarray(pts, dtype=np.float64)
    points /= np.linalg.norm(points, axis=1, keepdims=True)
    tri_arr = np.asarray(tris, dtype=np.int64)

    rounded = np.round(points, 6)
    _, first, inverse = np.unique(rounded, axis=0, return_index=True, return_inverse=True)
    unique_points = points[first]
    remapped_tris = inverse[tri_arr]
    return unique_points, remapped_tris


def build_lattice(frequency: int) -> dict[str, np.ndarray]:
    """Build the shell lattice at the given subdivision frequency (deterministic)."""
    if frequency < 2:
        raise ValueError("frequency must be >= 2")
    ico_v, ico_f = icosahedron()
    centers, tris = _subdivide(ico_v, ico_f, frequency)
    n = len(centers)
    expected = 10 * frequency * frequency + 2
    if n != expected:
        raise AssertionError(f"dedupe produced {n} cells, expected {expected}")

    # adjacency from triangle edges
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    degree = np.zeros(n, dtype=np.int32)
    neighbors = np.full((n, 6), -1, dtype=np.int32)
    for a, b in edges:
        neighbors[a, degree[a]] = b
        neighbors[b, degree[b]] = a
        degree[a] += 1
        degree[b] += 1

    pentagons = np.flatnonzero(degree == 5).astype(np.int32)
    if len(pentagons) != 12 or not np.all((degree == 5) | (degree == 6)):
        raise AssertionError("bad lattice: expected exactly 12 degree-5 cells, rest degree-6")

    # areas: 1/3 of incident (flat) triangle area, accumulated per vertex
    p0, p1, p2 = centers[tris[:, 0]], centers[tris[:, 1]], centers[tris[:, 2]]
    tri_area = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    areas = np.zeros(n, dtype=np.float64)
    for col in range(3):
        np.add.at(areas, tris[:, col], tri_area / 3.0)

    # tangent frames: n = center; t1 ⟂ n (seeded from world-Z, fallback X at poles)
    normal = centers
    ref = np.tile(np.array([0.0, 0.0, 1.0]), (n, 1))
    ref[np.abs(normal[:, 2]) > 0.9] = (1.0, 0.0, 0.0)
    t1 = np.cross(ref, normal)
    t1 /= np.linalg.norm(t1, axis=1, keepdims=True)
    t2 = np.cross(normal, t1)
    frames = np.stack([t1, t2, normal], axis=1)

    return {
        "centers": centers.astype(np.float32),
        "frames": frames.astype(np.float32),
        "areas": areas.astype(np.float32),
        "neighbors": neighbors,
        "pentagons": pentagons,
    }
