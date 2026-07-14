"""Equirect statemaps: the far-field animation, and human-viewable previews.

Data maps (statemap_####.png, RGB, one per 24 film frames):
  R = state * 85          (VOID 0 / TRUSS 85 / PLATE 170 / LIVE 255)
  G = stage progress * 255
  B = per-cell hash        (stable variation channel for shading)

Blender maps these onto the far-layer sphere (emission, alpha, roughness).
Equirect convention: u∈[0,1) → longitude φ = 2πu − π; v∈[0,1] → latitude
θ = π(0.5 − v); dir = (cosθcosφ, cosθsinφ, sinθ). Documented here = the
contract for build_scene.py's UV mapping.

Previews (preview_####.png + preview_strip.png) are colorized for eyeballs:
void near-black, truss ember-orange by progress, plate steel, live = dark
panel + city-light glitter from the hash channel.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

from . import N_FRAMES
from .construction import LIVE, PLATE, TRUSS, progress_at, state_at


def pixel_to_cell(centers: np.ndarray, width: int, height: int) -> np.ndarray:
    """(H, W) int32 map from equirect pixel to nearest lattice cell."""
    u = (np.arange(width) + 0.5) / width
    v = (np.arange(height) + 0.5) / height
    phi = 2.0 * np.pi * u - np.pi
    theta = np.pi * (0.5 - v)
    ct, st = np.cos(theta)[:, None], np.sin(theta)[:, None]
    dirs = np.empty((height, width, 3), dtype=np.float64)
    dirs[..., 0] = ct * np.cos(phi)[None, :]
    dirs[..., 1] = ct * np.sin(phi)[None, :]
    dirs[..., 2] = st
    tree = cKDTree(centers.astype(np.float64))
    _, idx = tree.query(dirs.reshape(-1, 3), workers=-1)
    return idx.reshape(height, width).astype(np.int32)


def city_field(lattice: dict[str, np.ndarray], seed: int, passes: int = 4) -> np.ndarray:
    """Spatially correlated per-cell uint8 field: city-light density.

    White noise smoothed over the adjacency graph a few times, then
    contrast-stretched — lights cluster into archipelagos instead of
    salt-and-pepper. Doubles as the statemap's B (variation) channel.
    """
    rng = np.random.default_rng(seed ^ 0xC0FFEE)
    neighbors = lattice["neighbors"]
    valid = neighbors >= 0
    field = rng.random(len(neighbors))
    for _ in range(passes):
        neigh_sum = np.where(valid, field[np.where(valid, neighbors, 0)], 0.0).sum(axis=1)
        field = 0.5 * field + 0.5 * neigh_sum / valid.sum(axis=1)
    lo, hi = np.percentile(field, (5, 95))
    field = np.clip((field - lo) / (hi - lo), 0.0, 1.0)
    return (field * 255).astype(np.uint8)


def render_statemaps(
    lattice: dict[str, np.ndarray],
    ca: dict[str, np.ndarray],
    out_dir: Path,
    seed: int,
    every: int = 24,
    size: tuple[int, int] = (4096, 2048),
    preview_scale: int = 2,
) -> list[Path]:
    """Write data maps + previews for frames 1, 1+every, ...; return data map paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    width, height = size
    pix = pixel_to_cell(lattice["centers"], width, height)
    hashes = city_field(lattice, seed)

    frames = list(range(1, N_FRAMES + 1, every))
    if frames[-1] != N_FRAMES:
        frames.append(N_FRAMES)

    paths = []
    previews = []
    for f in frames:
        state = state_at(ca, f)
        prog = progress_at(ca, f)
        rgb = np.empty((height, width, 3), dtype=np.uint8)
        rgb[..., 0] = (state * 85)[pix]
        rgb[..., 1] = (prog * 255).astype(np.uint8)[pix]
        rgb[..., 2] = hashes[pix]
        path = out_dir / f"statemap_{f:04d}.png"
        Image.fromarray(rgb).save(path)
        paths.append(path)

        pv = _colorize(state, prog, hashes)[pix][::preview_scale, ::preview_scale]
        pv_img = Image.fromarray(pv)
        pv_img.save(out_dir / f"preview_{f:04d}.png")
        previews.append(pv_img)

    _strip(previews, out_dir / "preview_strip.png")
    return paths


def _colorize(state: np.ndarray, prog: np.ndarray, hashes: np.ndarray) -> np.ndarray:
    """Per-cell preview color (N, 3) uint8."""
    n = len(state)
    h01 = hashes.astype(np.float32) / 255.0
    col = np.zeros((n, 3), dtype=np.float32)
    col[:] = (8, 8, 16)  # VOID: near-black space
    m = state == TRUSS  # ember orange, brightening with progress
    col[m] = np.outer(0.35 + 0.65 * prog[m], (230, 110, 25))
    m = state == PLATE  # steel blue-grey
    col[m] = np.outer(0.6 + 0.4 * prog[m], (70, 82, 105))
    m = state == LIVE  # dark panel + clustered city light (smoothstep on the field)
    t = np.clip((h01[m] - 0.55) / 0.30, 0.0, 1.0)
    lit = t * t * (3.0 - 2.0 * t)
    col[m] = (28, 34, 48) + np.outer(lit, (255, 216, 140) - np.array((28, 34, 48)))
    return np.clip(col, 0, 255).astype(np.uint8)


def _strip(previews: list[Image.Image], path: Path, count: int = 6) -> None:
    """Filmstrip of `count` evenly spaced previews, for one-glance review."""
    picks = [previews[round(i * (len(previews) - 1) / (count - 1))] for i in range(count)]
    w, h = picks[0].size
    strip = Image.new("RGB", (w * count + 2 * (count + 1), h + 4), (17, 17, 17))
    for i, im in enumerate(picks):
        strip.paste(im, (2 + i * (w + 2), 2))
    strip.save(path)
