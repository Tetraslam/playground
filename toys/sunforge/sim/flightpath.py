"""Flight path + corridor + cell polygons (DESIGN.md §2.5, §3).

Corridor: the band of cells the camera flies over, plus exact dual-cell
polygons for the near-layer geometry (corner k = projected barycenter of
consecutive neighbor triples; corners are shared between adjacent cells, so
the near layer tiles seamlessly).

Path (M4): the ship's 2880-frame trajectory, staged against the sim —
control points are *frontier-relative* (found from ca.npz like the Blender
cameras do), so a re-seeded shell restages the whole film. Shot legs follow
DESIGN.md §1; altitudes are clearance-checked against what is actually
built under each frame (state at pass time), banking comes from lateral
acceleration, and a seeded gaussian-smoothed micro-shake sits on top,
amplified at low altitude.

Outputs:
  renders/data/corridor.npz   ids / offsets / corners
  renders/data/path.npz       pos (N,3), quat (N,4) wxyz camera convention
                              (-Z forward, +Y up), theta/alt (debug),
                              dock_cell ()
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d

from . import N_FRAMES

GAP_AXIS = np.array([1.0, 0.0, 0.0])
SHELL_R = 2000.0

# clearance heights per state (VOID, TRUSS, PLATE, LIVE), pentagons override
STATE_CLEARANCE = np.array([0.0, 12.0, 10.0, 24.0])
FOUNDRY_CLEARANCE = 52.0


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


# ------------------------------------------------------------------- the path
def _frontier(centers: np.ndarray, done: np.ndarray, radius_deg: float = 6.0) -> float:
    """Largest gap-axis angle where local done-fraction drops below 0.5."""
    for theta in np.arange(178.0, 40.0, -1.0):
        t = np.radians(theta)
        p = np.array([np.cos(t), np.sin(t), 0.0])
        near = centers @ p > np.cos(np.radians(radius_deg))
        if near.any() and float(done[near].mean()) < 0.5:
            return float(theta)
    return 76.0


def _curve(controls: list[tuple[int, float]], sigma: float = 55.0) -> np.ndarray:
    """Per-frame curve through (frame, value) controls: lerp + gaussian smooth
    (C¹-smooth, no overshoot — good enough for a flight path)."""
    frames, values = zip(*controls, strict=True)
    raw = np.interp(np.arange(1, N_FRAMES + 1), frames, values)
    return gaussian_filter1d(raw, sigma, mode="nearest")


def _on_shell(theta: np.ndarray, around: np.ndarray) -> np.ndarray:
    """(N,3) unit directions from polar angle (from +X) and spin about +X."""
    t, a = np.radians(theta), np.radians(around)
    return np.stack([np.cos(t), np.sin(t) * np.cos(a), np.sin(t) * np.sin(a)], axis=1)


def _quat_from_basis(right: np.ndarray, up: np.ndarray, back: np.ndarray) -> np.ndarray:
    """(N,4) wxyz quaternions from orthonormal camera bases (columns r,u,b)."""
    m = np.stack([right, up, back], axis=2)  # (N,3,3), columns
    w = np.sqrt(np.maximum(0.0, 1.0 + m[:, 0, 0] + m[:, 1, 1] + m[:, 2, 2])) / 2.0
    w = np.maximum(w, 1e-9)
    x = (m[:, 2, 1] - m[:, 1, 2]) / (4 * w)
    y = (m[:, 0, 2] - m[:, 2, 0]) / (4 * w)
    z = (m[:, 1, 0] - m[:, 0, 1]) / (4 * w)
    q = np.stack([w, x, y, z], axis=1)
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def build_path(
    lattice: dict[str, np.ndarray], ca: dict[str, np.ndarray], seed: int
) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed ^ 0x5A11)
    centers = lattice["centers"].astype(np.float64)
    frames_idx = np.arange(1, N_FRAMES + 1)

    solid = _frontier(centers, ca["t_plate"] <= 1)
    band = _frontier(centers, ca["t_truss"] <= 1)
    live = _frontier(centers, ca["t_live"] <= 1)

    # dock: the corridor foundry spire nearest the solid frontier
    cor_ids = provisional_corridor(lattice)
    spire_ids = np.intersect1d(cor_ids, lattice["pentagons"])
    spire_theta = np.degrees(np.arccos(np.clip(centers[spire_ids, 0], -1, 1)))
    dock_cell = int(spire_ids[np.argmin(np.abs(spire_theta - solid))])
    dock_dir = centers[dock_cell]
    dock_theta = float(np.degrees(np.arccos(np.clip(dock_dir[0], -1, 1))))
    # park BESIDE the spire at spire-top height (clearance must not fight
    # the docking: the offset keeps us out of the stack, alt 46 ≈ clamp level)
    dock_around = float(np.degrees(np.arctan2(dock_dir[2], dock_dir[1]))) + 0.8

    # shot legs (DESIGN.md §1), frontier-relative
    theta = _curve(
        [
            (1, live + 40.0),
            (360, live + 10.0),
            (768, solid + 8.0),
            (1248, band - 1.0),
            (1728, band - 26.0),
            (2160, band - 8.0),
            (2640, solid + 1.0),
            (2880, dock_theta),
        ]
    )
    around = _curve(
        [
            (1, -1.0),
            (768, 1.0),
            (1248, -1.0),
            (1728, 3.5),
            (2160, 6.0),
            (2640, 4.0),
            (2880, dock_around),
        ]
    )
    around += 0.9 * np.sin(frames_idx / 260.0)  # gentle weave for banking life
    alt = _curve(
        [
            (1, 220.0),
            (360, 90.0),
            (768, 26.0),
            (1248, 14.0),
            (1728, 44.0),
            (2160, 18.0),
            (2640, 16.0),
            (2880, 46.0),
        ],
        sigma=45.0,
    )

    # clearance: at each frame, hold altitude above whatever is built below
    # *at pass time* (foundries are always tall)
    dirs = _on_shell(theta, around)
    pentagons = set(int(p) for p in lattice["pentagons"])
    state_h = np.zeros(len(centers))
    for f in range(0, N_FRAMES, 24):  # re-check every second
        fr = f + 1
        s = np.zeros(len(centers), dtype=np.int64)
        s[ca["t_truss"] <= fr] = 1
        s[ca["t_plate"] <= fr] = 2
        s[ca["t_live"] <= fr] = 3
        state_h = STATE_CLEARANCE[s]
        state_h[list(pentagons)] = FOUNDRY_CLEARANCE
        near = centers @ dirs[f] > np.cos(np.radians(1.6))
        if near.any():
            need = state_h[near].max() + 6.0
            alt[max(0, f - 36) : min(N_FRAMES, f + 36)] = np.maximum(
                alt[max(0, f - 36) : min(N_FRAMES, f + 36)], need
            )
    alt = np.maximum(gaussian_filter1d(alt, 24.0, mode="nearest"), alt)

    pos = dirs * (SHELL_R + alt)[:, None]

    # micro-shake: gaussian-smoothed noise, louder when low
    shake_amp = 0.05 * (1.0 + 30.0 / np.maximum(alt, 8.0))
    shake = gaussian_filter1d(rng.standard_normal((N_FRAMES, 3)), 7.0, axis=0, mode="nearest")
    shake /= np.abs(shake).max() + 1e-9
    pos = pos + shake * shake_amp[:, None]

    # orientation: forward from the (unshaken) path, radial up, banked roll
    fwd = np.gradient(dirs * (SHELL_R + alt)[:, None], axis=0)
    # final approach: blend forward toward the spire's clamp level
    to_dock = dock_dir * (SHELL_R + 42.0) - pos
    blend = np.clip((frames_idx - (N_FRAMES - 420)) / 420.0, 0.0, 1.0)[:, None]
    fwd = fwd / (np.linalg.norm(fwd, axis=1, keepdims=True) + 1e-9)
    to_dock /= np.linalg.norm(to_dock, axis=1, keepdims=True) + 1e-9
    fwd = fwd * (1.0 - blend) + to_dock * blend
    fwd /= np.linalg.norm(fwd, axis=1, keepdims=True) + 1e-9

    up_hint = dirs
    right = np.cross(fwd, up_hint)
    right /= np.linalg.norm(right, axis=1, keepdims=True) + 1e-9
    up = np.cross(right, fwd)

    accel = np.gradient(np.gradient(pos, axis=0), axis=0)
    lateral = np.einsum("ij,ij->i", accel, right)
    roll = np.clip(gaussian_filter1d(-lateral * 260.0, 18.0, mode="nearest"), -0.5, 0.5)
    roll += (
        0.004
        * gaussian_filter1d(rng.standard_normal(N_FRAMES), 9.0, mode="nearest")
        * (shake_amp / shake_amp.min())
    )
    cr, sr = np.cos(roll)[:, None], np.sin(roll)[:, None]
    right_r = right * cr + up * sr
    up_r = up * cr - right * sr

    quat = _quat_from_basis(right_r, up_r, -fwd)
    # hemisphere continuity (kill double-cover sign flips; motion blur cares)
    flips = np.cumsum(np.einsum("ij,ij->i", quat[1:], quat[:-1]) < 0) % 2
    quat[1:][flips == 1] *= -1.0
    return {
        "pos": pos.astype(np.float32),
        "quat": quat.astype(np.float32),
        "theta": theta.astype(np.float32),
        "alt": alt.astype(np.float32),
        "dock_cell": np.int32(dock_cell),
    }
