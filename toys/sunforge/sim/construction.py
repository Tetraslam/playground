"""Construction CA on the shell lattice (DESIGN.md §2.2).

Model: first-passage percolation — multi-source Dijkstra from the 12 foundry
pentagons over lognormal-noised edge weights. Random edge weights make the
growth *identical* to a stochastic spreading CA but give us the entire
history in one pass: per cell, the abstract arrival time. Stage dwells
(TRUSS → PLATE → LIVE) stack on top with their own noise.

Staging the film: foundries get start offsets biased along GAP_AXIS, so one
side of the shell finished long ago (S1's dark city-lit hemisphere) and the
opposite side hasn't started (S4's great aperture). The calibration then
places the film's 2880 frames so the front visibly advances.

Output (renders/data/ca.npz): per-cell stage-entry times in FILM FRAMES
(float32; negative = before the film, > N_FRAMES = after / never ≈ +inf).
  t_truss, t_plate, t_live  (N,)
"""

from __future__ import annotations

import heapq

import numpy as np

from . import N_FRAMES

VOID, TRUSS, PLATE, LIVE = 0, 1, 2, 3

GAP_AXIS = np.array([1.0, 0.0, 0.0])  # the great aperture ends up around +X

# tuning knobs (abstract-time noise / film-frame pacing)
EDGE_SIGMA = 0.55  # lognormal σ for edge weights — front raggedness
STAGGER_SPREAD = 6.0  # foundry start offsets, in units of median shell-crossing time
BUILT_FRACTION_AT_START = 0.62  # cells with truss present at frame 1
FRONT_ADVANCE = 0.025  # additional fraction trussed by frame 2880
# dwells are LONG relative to the film (the front only advances ~2.5% of the
# shell in 2 min): a wide construction band trails the frontier, so S2/S3 fly
# over trusses and half-plated cells, not a razor-thin edge.
TRUSS_DWELL_FRAMES = 3.0 * N_FRAMES  # median truss -> plate
PLATE_DWELL_FRAMES = 6.0 * N_FRAMES  # median plate -> live
DWELL_SIGMA = 0.5


def _multi_source_dijkstra(
    neighbors: np.ndarray, sources: np.ndarray, source_offsets: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    """Arrival time per cell from the earliest foundry, over noisy edge weights."""
    n = len(neighbors)
    # symmetric per-edge weights: draw once per undirected edge
    weights = {}
    for a in range(n):
        for b in neighbors[a]:
            if b >= 0 and a < b:
                weights[(a, b)] = rng.lognormal(mean=0.0, sigma=EDGE_SIGMA)
    dist = np.full(n, np.inf)
    heap: list[tuple[float, int]] = []
    for s, off in zip(sources, source_offsets, strict=True):
        dist[s] = off
        heapq.heappush(heap, (off, int(s)))
    while heap:
        d, a = heapq.heappop(heap)
        if d > dist[a]:
            continue
        for b in neighbors[a]:
            if b < 0:
                continue
            w = weights[(a, b) if a < b else (b, a)]
            nd = d + w
            if nd < dist[b]:
                dist[b] = nd
                heapq.heappush(heap, (nd, int(b)))
    return dist


def run_ca(lattice: dict[str, np.ndarray], seed: int) -> dict[str, np.ndarray]:
    """Full construction history, calibrated to film frames. Deterministic in seed."""
    rng = np.random.default_rng(seed)
    centers = lattice["centers"].astype(np.float64)
    foundries = lattice["pentagons"]

    # stagger: foundries on the -GAP_AXIS side started long ago
    alignment = (centers[foundries] @ GAP_AXIS + 1.0) / 2.0  # 0 (far side) .. 1 (gap side)
    # median cell-to-cell hop is ~1.0; shell crossing ~ π / mean_hop_angle hops.
    n_hops_across = np.pi / np.sqrt(4 * np.pi / len(centers))
    offsets = alignment * STAGGER_SPREAD * n_hops_across

    arrival = _multi_source_dijkstra(lattice["neighbors"], foundries, offsets, rng)

    # calibration: film window in abstract time from build-fraction quantiles
    q0 = np.quantile(arrival, BUILT_FRACTION_AT_START)
    q1 = np.quantile(arrival, BUILT_FRACTION_AT_START + FRONT_ADVANCE)
    per_frame = (q1 - q0) / N_FRAMES
    t_truss = (arrival - q0) / per_frame  # film frames, frame 1 ≈ quantile crossing

    n = len(t_truss)
    dwell1 = TRUSS_DWELL_FRAMES * rng.lognormal(0.0, DWELL_SIGMA, n)
    dwell2 = PLATE_DWELL_FRAMES * rng.lognormal(0.0, DWELL_SIGMA, n)
    t_plate = t_truss + dwell1
    t_live = t_plate + dwell2

    return {
        "t_truss": t_truss.astype(np.float32),
        "t_plate": t_plate.astype(np.float32),
        "t_live": t_live.astype(np.float32),
    }


def state_at(ca: dict[str, np.ndarray], frame: float) -> np.ndarray:
    """Per-cell state (uint8) at a film frame."""
    s = np.zeros(len(ca["t_truss"]), dtype=np.uint8)
    s[ca["t_truss"] <= frame] = TRUSS
    s[ca["t_plate"] <= frame] = PLATE
    s[ca["t_live"] <= frame] = LIVE
    return s


def progress_at(ca: dict[str, np.ndarray], frame: float) -> np.ndarray:
    """Per-cell progress 0..1 within the current stage (LIVE saturates at 1)."""
    t_t, t_p, t_l = ca["t_truss"], ca["t_plate"], ca["t_live"]
    s = state_at(ca, frame)
    prog = np.zeros(len(t_t), dtype=np.float32)
    m = s == TRUSS
    prog[m] = (frame - t_t[m]) / np.maximum(t_p[m] - t_t[m], 1e-3)
    m = s == PLATE
    prog[m] = (frame - t_p[m]) / np.maximum(t_l[m] - t_p[m], 1e-3)
    prog[s == LIVE] = 1.0
    return np.clip(prog, 0.0, 1.0)
