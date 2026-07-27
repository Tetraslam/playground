"""persist — persistent homology from scratch, on things that move.

Computes Vietoris–Rips persistent homology with no topology library: builds
the flag complex by bitmask clique expansion, orders simplices into a
filtration, and runs the boundary-matrix reduction over GF(2) by hand. Feed
it a point cloud (circle, figure-eight, torus, clusters) or a 1D time series
(Lorenz, or the orderbook toy's price tape) via a Takens sliding-window
embedding, and it tells you how many loops the thing has — as a barcode, a
persistence diagram, and an animated filtration sweep where you watch holes
being born and die.

    uv run python toys/persist/main.py --cloud circle --out scratch/circle.svg
    uv run python toys/persist/main.py --cloud figure-eight --animate scratch/f8_frames \
        --anim-out scratch/f8_sweep
    uv run python toys/persist/main.py --series lorenz --out scratch/lorenz.svg
    uv run python toys/persist/main.py --series orderbook --out scratch/tape.svg
    uv run python toys/persist/main.py --cloud torus --max-hom-dim 2 --n 90 --print
    # view: rsvg-convert scratch/circle.svg -o scratch/circle.png

Stdlib + numpy. Drawn from the seed-bank topic "topological data analysis".
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import math
import os
import subprocess
import sys

import numpy as np

DIM_COLORS = {0: "#3fb950", 1: "#58a6ff", 2: "#d2a8ff"}
DIM_NAMES = {0: "H0 (components)", 1: "H1 (loops)", 2: "H2 (voids)"}
BG = "#0d1117"
FG = "#c9d1d9"
MUTED = "#8b949e"
EDGE = "#21262d"


class Rng:
    """Deterministic splitmix64 PRNG seeded from a string."""

    def __init__(self, seed: str):
        self.s = int.from_bytes(hashlib.blake2b(seed.encode(), digest_size=8).digest(), "little")

    def _next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def rand(self) -> float:
        return (self._next() >> 11) / float(1 << 53)

    def gauss(self) -> float:
        u1 = max(1e-9, self.rand())
        u2 = self.rand()
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


# ---------------------------------------------------------------------------
# generators: point clouds and time series
# ---------------------------------------------------------------------------


def cloud_circle(n: int, noise: float, rng: Rng) -> np.ndarray:
    pts = []
    for _ in range(n):
        t = rng.rand() * 2 * math.pi
        r = 1.0 + noise * rng.gauss()
        pts.append((r * math.cos(t), r * math.sin(t)))
    return np.array(pts)


def cloud_figure_eight(n: int, noise: float, rng: Rng) -> np.ndarray:
    # lemniscate of Gerono: x = cos t, y = sin t cos t — two loops, one crossing
    pts = []
    for _ in range(n):
        t = rng.rand() * 2 * math.pi
        pts.append(
            (math.cos(t) + noise * rng.gauss(), math.sin(t) * math.cos(t) + noise * rng.gauss())
        )
    return np.array(pts)


def cloud_torus(n: int, noise: float, rng: Rng) -> np.ndarray:
    # area-uniform sampling: accept v with prob ∝ (R + r cos v), else the
    # inner rim gets oversampled and the Rips complex tears there
    big_r, small_r = 1.6, 0.7
    pts = []
    while len(pts) < n:
        u = rng.rand() * 2 * math.pi
        v = rng.rand() * 2 * math.pi
        if rng.rand() * (big_r + small_r) > big_r + small_r * math.cos(v):
            continue
        pts.append(
            (
                (big_r + small_r * math.cos(v)) * math.cos(u) + noise * rng.gauss(),
                (big_r + small_r * math.cos(v)) * math.sin(u) + noise * rng.gauss(),
                small_r * math.sin(v) + noise * rng.gauss(),
            )
        )
    return np.array(pts)


def cloud_clusters(n: int, noise: float, rng: Rng) -> np.ndarray:
    centers = [(0.0, 0.0), (6.0, 1.0), (2.0, 5.5)]
    pts = []
    for i in range(n):
        cx, cy = centers[i % len(centers)]
        pts.append((cx + 0.4 * rng.gauss(), cy + 0.4 * rng.gauss()))
    return np.array(pts)


CLOUDS = {
    "circle": cloud_circle,
    "figure-eight": cloud_figure_eight,
    "torus": cloud_torus,
    "clusters": cloud_clusters,
}


def series_lorenz(steps: int, rng: Rng) -> np.ndarray:
    """x-component of the Lorenz attractor, RK4-integrated."""

    def f(p):
        x, y, z = p
        return (10.0 * (y - x), x * (28.0 - z) - y, x * y - 8.0 / 3.0 * z)

    dt = 0.01
    p = (1.0 + 0.01 * rng.gauss(), 1.0, 1.0)
    out = []
    for i in range(steps + 4000):
        k1 = f(p)
        k2 = f(tuple(p[j] + dt / 2 * k1[j] for j in range(3)))
        k3 = f(tuple(p[j] + dt / 2 * k2[j] for j in range(3)))
        k4 = f(tuple(p[j] + dt * k3[j] for j in range(3)))
        p = tuple(p[j] + dt / 6 * (k1[j] + 2 * k2[j] + 2 * k3[j] + k4[j]) for j in range(3))
        if i >= 4000:  # burn-in
            out.append(p[0])
    return np.array(out)


def series_orderbook(seed: str, steps: int) -> np.ndarray:
    """Mid-price history from the orderbook toy, loaded by path (composition
    without coupling: persist reaches into the other toy's simulate())."""
    path = os.path.join(os.path.dirname(__file__), "..", "orderbook", "main.py")
    spec = importlib.util.spec_from_file_location("orderbook_main", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass looks up its module here
    spec.loader.exec_module(mod)
    book = mod.simulate(seed=seed, steps=steps, true_value=100)
    mids = np.array(book.mid_history, dtype=float)
    # z-score: prices are integer ticks in a tight band; without rescaling the
    # Takens cloud collapses onto a lattice blob and eps auto-tunes to noise.
    return (mids - mids.mean()) / max(mids.std(), 1e-9)


SERIES = {"lorenz": series_lorenz, "orderbook": series_orderbook}


def takens(series: np.ndarray, tau: int, dim: int) -> np.ndarray:
    """Sliding-window (delay) embedding: series -> point cloud in R^dim."""
    n = len(series) - (dim - 1) * tau
    return np.column_stack([series[k * tau : k * tau + n] for k in range(dim)])


# ---------------------------------------------------------------------------
# vietoris–rips complex: bitmask clique expansion
# ---------------------------------------------------------------------------


def adjacency_bitmasks(dmat: np.ndarray, eps: float) -> list[int]:
    n = len(dmat)
    adj = [0] * n
    for i in range(n):
        row = dmat[i]
        for j in range(i + 1, n):
            if row[j] <= eps:
                adj[i] |= 1 << j
                adj[j] |= 1 << i
    return adj


def above(x: int, k: int) -> int:
    """Bitmask of the set bits of x strictly above index k."""
    return x & ~((1 << (k + 1)) - 1)


def count_simplices(adj: list[int], top_dim: int) -> int:
    """Total simplices (all dimensions up to top_dim) in the flag complex."""
    n = len(adj)
    total = n
    edges = 0
    tris = 0
    tets = 0
    for i in range(n):
        ai = adj[i]
        m = above(ai, i)
        while m:
            b = m & -m
            j = b.bit_length() - 1
            m ^= b
            edges += 1
            if top_dim >= 2:
                common = above(ai & adj[j], j)
                tris += bin(common).count("1")
                if top_dim >= 3:
                    mm = common
                    while mm:
                        bb = mm & -mm
                        k = bb.bit_length() - 1
                        mm ^= bb
                        tets += bin(above(ai & adj[j] & adj[k], k)).count("1")
    return total + edges + tris + tets


def choose_eps(dmat: np.ndarray, budget: int, top_dim: int) -> float:
    """Largest epsilon whose complex stays within the simplex budget."""
    n = len(dmat)
    weights = sorted({float(dmat[i, j]) for i in range(n) for j in range(i + 1, n)})
    candidates = weights[:: max(1, len(weights) // 300)]
    lo, hi = 0, len(candidates) - 1
    best = candidates[0]
    while lo <= hi:
        mid = (lo + hi) // 2
        eps = candidates[mid]
        if count_simplices(adjacency_bitmasks(dmat, eps), top_dim) <= budget:
            best = eps
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def build_complex(dmat: np.ndarray, eps: float, top_dim: int):
    """All simplices of the Rips complex at eps, in filtration order.

    Returns a list of (filtration_value, dim, vertex_tuple) sorted by
    (value, dim, vertices) — a valid filtration: every face precedes its
    cofaces (equal value ties broken by lower dimension first).
    """
    n = len(dmat)
    adj = adjacency_bitmasks(dmat, eps)
    sims = [(0.0, 0, (i,)) for i in range(n)]

    def w(a, b):
        return float(dmat[a, b])

    for i in range(n):
        ai = adj[i]
        m = above(ai, i)
        while m:
            b = m & -m
            j = b.bit_length() - 1
            m ^= b
            wij = w(i, j)
            sims.append((wij, 1, (i, j)))
            if top_dim >= 2:
                common = above(ai & adj[j], j)
                mm = common
                while mm:
                    bb = mm & -mm
                    k = bb.bit_length() - 1
                    mm ^= bb
                    wik = w(i, k)
                    wjk = w(j, k)
                    w3 = max(wij, wik, wjk)
                    sims.append((w3, 2, (i, j, k)))
                    if top_dim >= 3:
                        lm = above(ai & adj[j] & adj[k], k)
                        while lm:
                            bl = lm & -lm
                            ell = bl.bit_length() - 1
                            lm ^= bl
                            w4 = max(w3, w(i, ell), w(j, ell), w(k, ell))
                            sims.append((w4, 3, (i, j, k, ell)))
    sims.sort(key=lambda s: (s[0], s[1], s[2]))
    return sims


# ---------------------------------------------------------------------------
# the reduction: boundary matrix over GF(2), by hand
# ---------------------------------------------------------------------------


def reduce_boundary(sims, top_dim: int) -> list[tuple[int, float, float | None]]:
    """Standard matrix reduction. Returns classes as (dim, birth, death|None).

    A column that reduces to empty *creates* a class; a column whose reduced
    lowest row is i *kills* the class born at simplex i. Creators never
    killed are essential (death = None).
    """
    index = {s[2]: pos for pos, s in enumerate(sims)}
    low_to_col: dict[int, set[int]] = {}
    pairs: list[tuple[int, int]] = []
    creators: list[int] = []

    for j, (_, dim, verts) in enumerate(sims):
        if dim == 0:
            creators.append(j)
            continue
        col = {index[verts[:m] + verts[m + 1 :]] for m in range(len(verts))}
        while col:
            low = max(col)
            pivot = low_to_col.get(low)
            if pivot is None:
                break
            col ^= pivot
        if col:
            low = max(col)
            low_to_col[low] = col
            pairs.append((low, j))
        else:
            creators.append(j)

    classes = []
    paired_births = set()
    for b, d in pairs:
        vb, db, _ = sims[b]
        vd, _, _ = sims[d]
        classes.append((db, vb, vd))
        paired_births.add(b)
    for c in creators:
        if c not in paired_births:
            vc, dc, _ = sims[c]
            classes.append((dc, vc, None))
    # classes at top_dim are truncation artifacts: with no (top_dim+1)-
    # simplices in the complex, nothing can kill them, so they ALL look
    # essential. Drop everything above max_hom_dim.
    max_hom_dim = top_dim - 1
    return [c for c in classes if c[0] <= max_hom_dim]


# ---------------------------------------------------------------------------
# svg views
# ---------------------------------------------------------------------------


def project2d(pts: np.ndarray) -> np.ndarray:
    centered = pts - pts.mean(axis=0)
    if pts.shape[1] > 2:
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        centered = centered @ vt[:2].T
    span = np.ptp(centered, axis=0).max()
    return (centered - centered.min(axis=0)) / max(span, 1e-9)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;")


def fmt(v: float) -> str:
    return f"{v:.2f}"


def cloud_dots(xy: np.ndarray, x0: float, y0: float, w: float, h: float, r: float = 2.2):
    for px, py in xy:
        yield f'<circle cx="{x0 + px * w:.1f}" cy="{y0 + (1 - py) * h:.1f}" r="{r}" fill="{FG}" opacity="0.75"/>'


def barcode_rows(classes, dim, max_rows):
    """Top rows for one homology dimension: essentials first, then by
    persistence descending. Zero-length bars (born and dead at the same
    filtration value — triangle spam) are dropped: they'd draw as nothing."""
    rows = [c for c in classes if c[0] == dim and (c[2] is None or c[2] - c[1] > 1e-9)]
    rows.sort(key=lambda c: (c[2] is not None, -(c[2] - c[1]) if c[2] is not None else 0, c[1]))
    hidden = max(0, len(rows) - max_rows)
    max_hidden = 0.0
    if hidden:
        cut = rows[max_rows:]
        max_hidden = (
            max((c[2] - c[1]) for c in cut if c[2] is not None) if any(c[2] for c in cut) else 0.0
        )
        rows = rows[:max_rows]
    return rows, hidden, max_hidden


def svg_panel(pts, classes, eps_max, title, subtitle, max_rows=(14, 22, 8)):
    W, H = 1560, 620
    pad = 26
    col_w = (W - 4 * pad) / 3
    top = 84
    panel_h = H - top - pad
    xy = project2d(pts)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        f'<text x="{pad}" y="{pad + 8}" fill="{FG}" font-family="monospace" font-size="20">{esc(title)}</text>',
        f'<text x="{pad}" y="{pad + 30}" fill="{MUTED}" font-family="monospace" font-size="12">{esc(subtitle)}</text>',
    ]

    # --- left: the point cloud ---
    x0 = pad
    parts.append(
        f'<text x="{x0}" y="{top - 12}" fill="{MUTED}" font-family="monospace" font-size="13">the cloud (PCA)</text>'
    )
    parts.append(
        f'<rect x="{x0}" y="{top}" width="{col_w}" height="{panel_h}" fill="none" stroke="{EDGE}"/>'
    )
    inner = 14
    parts += list(cloud_dots(xy, x0 + inner, top + inner, col_w - 2 * inner, panel_h - 2 * inner))

    # --- middle: the barcode ---
    x1 = 2 * pad + col_w
    parts.append(
        f'<text x="{x1}" y="{top - 12}" fill="{MUTED}" font-family="monospace" font-size="13">the barcode</text>'
    )
    parts.append(
        f'<rect x="{x1}" y="{top}" width="{col_w}" height="{panel_h}" fill="none" stroke="{EDGE}"/>'
    )
    bx0, bx1 = x1 + 12, x1 + col_w - 12

    def sx(v):
        return bx0 + (v / eps_max) * (bx1 - bx0)

    y = top + 26
    for dim, cap in enumerate(max_rows):
        rows, hidden, max_hidden = barcode_rows(classes, dim, cap)
        if not rows:
            continue
        color = DIM_COLORS[dim]
        parts.append(
            f'<text x="{bx0}" y="{y - 8}" fill="{color}" font-family="monospace" font-size="12">{DIM_NAMES[dim]}</text>'
        )
        for _, birth, death in rows:
            y += 10
            if death is None:
                parts.append(
                    f'<line x1="{sx(birth):.1f}" y1="{y}" x2="{bx1 - 8:.1f}" y2="{y}" stroke="{color}" stroke-width="3"/>'
                    f'<path d="M {bx1 - 8:.1f} {y - 4} L {bx1:.1f} {y} L {bx1 - 8:.1f} {y + 4} Z" fill="{color}"/>'
                )
            else:
                parts.append(
                    f'<line x1="{sx(birth):.1f}" y1="{y}" x2="{sx(death):.1f}" y2="{y}" stroke="{color}" stroke-width="3"/>'
                )
        if hidden:
            y += 14
            parts.append(
                f'<text x="{bx0}" y="{y}" fill="{MUTED}" font-family="monospace" font-size="11">'
                f"+ {hidden} short bars (longest {fmt(max_hidden)})</text>"
            )
        y += 22
    for t in range(5):
        v = eps_max * t / 4
        parts.append(
            f'<text x="{sx(v):.1f}" y="{top + panel_h - 8}" fill="{MUTED}" font-family="monospace" font-size="10" text-anchor="middle">{fmt(v)}</text>'
        )

    # --- right: the persistence diagram ---
    x2 = 3 * pad + 2 * col_w
    parts.append(
        f'<text x="{x2}" y="{top - 12}" fill="{MUTED}" font-family="monospace" font-size="13">the diagram (birth × death)</text>'
    )
    parts.append(
        f'<rect x="{x2}" y="{top}" width="{col_w}" height="{panel_h}" fill="none" stroke="{EDGE}"/>'
    )
    dx0, dx1 = x2 + 12, x2 + col_w - 12
    dy0, dy1 = top + panel_h - 24, top + 12

    def ddx(v):
        return dx0 + (v / eps_max) * (dx1 - dx0)

    def ddy(v):
        return dy0 + (v / eps_max) * (dy1 - dy0)

    parts.append(
        f'<line x1="{ddx(0):.1f}" y1="{ddy(0):.1f}" x2="{ddx(eps_max):.1f}" y2="{ddy(eps_max):.1f}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4 3" opacity="0.5"/>'
    )
    for dim, birth, death in classes:
        color = DIM_COLORS[dim]
        if death is None:
            parts.append(
                f'<path d="M {ddx(birth):.1f} {ddy(eps_max) - 5} l 5 9 h -10 Z" fill="none" stroke="{color}" stroke-width="1.5"/>'
            )
        elif death - birth > eps_max * 0.01:
            parts.append(
                f'<circle cx="{ddx(birth):.1f}" cy="{ddy(death):.1f}" r="3.4" fill="{color}" opacity="0.8"/>'
            )
    parts.append(
        f'<text x="{ddx(0):.1f}" y="{dy0 + 16}" fill="{MUTED}" font-family="monospace" font-size="10">0</text>'
    )
    parts.append(
        f'<text x="{ddx(eps_max):.1f}" y="{dy0 + 16}" fill="{MUTED}" font-family="monospace" font-size="10" text-anchor="middle">{fmt(eps_max)}</text>'
    )

    parts.append("</svg>")
    return "\n".join(parts)


def svg_frame(xy, edges, classes, eps, eps_max, title):
    """One animation frame: complex grown to eps (left), barcode clipped at
    eps (right)."""
    W, H = 1240, 560
    pad = 24
    top = 64
    panel_h = H - top - pad
    left_w = 560
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        f'<text x="{pad}" y="{pad + 8}" fill="{FG}" font-family="monospace" font-size="17">{esc(title)}</text>',
        f'<text x="{pad}" y="{pad + 28}" fill="{MUTED}" font-family="monospace" font-size="12">epsilon = {eps:.3f} / {eps_max:.3f}</text>',
        f'<rect x="{pad}" y="{top}" width="{left_w}" height="{panel_h}" fill="none" stroke="{EDGE}"/>',
    ]
    inner = 14

    def cx(px):
        return pad + inner + px * (left_w - 2 * inner)

    def cy(py):
        return top + inner + (1 - py) * (panel_h - 2 * inner)

    for wgt, i, j in edges:
        if wgt > eps:
            break
        parts.append(
            f'<line x1="{cx(xy[i, 0]):.1f}" y1="{cy(xy[i, 1]):.1f}" x2="{cx(xy[j, 0]):.1f}" y2="{cy(xy[j, 1]):.1f}" stroke="#30363d" stroke-width="0.8"/>'
        )
    parts += list(
        cloud_dots(xy, pad + inner, top + inner, left_w - 2 * inner, panel_h - 2 * inner, r=2.4)
    )

    bx0 = pad + left_w + 60
    bx1 = W - pad - 10
    parts.append(
        f'<rect x="{bx0 - 14}" y="{top}" width="{bx1 - bx0 + 28}" height="{panel_h}" fill="none" stroke="{EDGE}"/>'
    )

    def sx(v):
        return bx0 + (min(v, eps_max) / eps_max) * (bx1 - bx0)

    y = top + 24
    for dim in range(3):
        rows, _, _ = barcode_rows(classes, dim, (14, 22, 8)[dim])
        if not rows:
            continue
        color = DIM_COLORS[dim]
        parts.append(
            f'<text x="{bx0}" y="{y - 6}" fill="{color}" font-family="monospace" font-size="11">{DIM_NAMES[dim]}</text>'
        )
        for _, birth, death in rows:
            if birth > eps:
                continue
            y += 9
            alive = death is None or death > eps
            end = eps if alive else death
            op = "0.95" if alive else "0.3"
            parts.append(
                f'<line x1="{sx(birth):.1f}" y1="{y}" x2="{sx(end):.1f}" y2="{y}" stroke="{color}" stroke-width="2.6" opacity="{op}"/>'
            )
        y += 20
    parts.append(
        f'<line x1="{sx(eps):.1f}" y1="{top + 6}" x2="{sx(eps):.1f}" y2="{top + panel_h - 6}" stroke="{FG}" stroke-width="1" opacity="0.55"/>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def main() -> None:
    ap = argparse.ArgumentParser(description="persistent homology from scratch")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--cloud", choices=list(CLOUDS), help="synthetic point cloud")
    src.add_argument("--series", choices=list(SERIES), help="1D time series -> Takens embedding")
    ap.add_argument("--n", type=int, default=None, help="cloud size (default: 220, 100 for torus)")
    ap.add_argument("--noise", type=float, default=0.05)
    ap.add_argument(
        "--tau", type=int, default=None, help="Takens delay (default: 12 lorenz, 30 orderbook)"
    )
    ap.add_argument("--embed-dim", type=int, default=3)
    ap.add_argument(
        "--steps", type=int, default=12000, help="series length (lorenz) or sim steps (orderbook)"
    )
    ap.add_argument("--series-seed", default="persist", help="seed passed to the series generator")
    ap.add_argument("--seed", default="holes", help="seed for clouds / lorenz init")
    ap.add_argument(
        "--max-hom-dim",
        type=int,
        default=1,
        choices=[1, 2],
        help="deepest homology dimension (2 needs tetrahedra: slow)",
    )
    ap.add_argument(
        "--eps-max",
        type=float,
        default=None,
        help="filtration cutoff (default: auto from --budget)",
    )
    ap.add_argument("--budget", type=int, default=60000, help="simplex budget for auto eps")
    ap.add_argument("--out", default=None, help="write summary panel SVG here")
    ap.add_argument("--animate", default=None, help="write animation frames to this dir")
    ap.add_argument(
        "--anim-out",
        default=None,
        help="encode webp/mp4/strip with this basename (needs --animate)",
    )
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--print", action="store_true", help="print the intervals")
    args = ap.parse_args()

    rng = Rng(args.seed)
    top_dim = args.max_hom_dim + 1  # simplices one dim above the homology we want deaths for

    if args.cloud:
        n = args.n or (100 if args.cloud == "torus" else 220)
        pts = CLOUDS[args.cloud](n, args.noise, rng)
        title = f"persist · cloud={args.cloud} · n={n} · noise={args.noise}"
    else:
        if args.series == "lorenz":
            series = series_lorenz(args.steps, rng)
        else:
            series = series_orderbook(args.series_seed, min(args.steps, 6000))
        tau = args.tau or (12 if args.series == "lorenz" else 30)
        cloud = takens(series, tau, args.embed_dim)
        n = args.n or 260
        idx = np.linspace(0, len(cloud) - 1, n).astype(int)
        pts = cloud[idx]
        title = f"persist · series={args.series} · tau={tau} · dim={args.embed_dim} · n={n}"

    dmat = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
    eps_max = args.eps_max or choose_eps(dmat, args.budget, top_dim)
    sims = build_complex(dmat, eps_max, top_dim)
    classes = reduce_boundary(sims, top_dim)

    n_simplices = len(sims)
    by_dim = {d: sum(1 for s in sims if s[1] == d) for d in range(top_dim + 1)}
    subtitle = (
        f"eps_max={eps_max:.3f} · simplices={n_simplices} "
        f"({', '.join(f'{by_dim[d]} x d{d}' for d in sorted(by_dim))}) · seed={args.seed}"
    )
    print(subtitle)

    if args.print:
        significant = [c for c in classes if c[2] is None or c[2] - c[1] > 1e-9]
        significant.sort(key=lambda c: (c[0], c[2] is not None, -(c[2] - c[1]) if c[2] else 0))
        for dim, birth, death in significant:
            pers = "essential" if death is None else f"pers={death - birth:.3f}"
            print(
                f"  H{dim}  {birth:.3f} -> {'inf' if death is None else f'{death:.3f}'}  ({pers})"
            )

    if args.out:
        write(args.out, svg_panel(pts, classes, eps_max, title, subtitle))
        print(f"wrote {args.out}")

    if args.animate:
        xy = project2d(pts)
        edges = sorted(
            (float(dmat[i, j]), i, j)
            for i in range(len(pts))
            for j in range(i + 1, len(pts))
            if dmat[i, j] <= eps_max
        )
        os.makedirs(args.animate, exist_ok=True)
        for f in range(args.frames):
            # quantile pacing: each frame adds ~the same number of edges, so
            # the sweep lingers in the sparse regime where holes live instead
            # of racing to the dense mush
            eps = edges[min(len(edges) - 1, int((f + 0.5) / args.frames * len(edges)))][0]
            svg_path = os.path.join(args.animate, f"frame_{f:03d}.svg")
            png_path = os.path.join(args.animate, f"frame_{f:03d}.png")
            write(svg_path, svg_frame(xy, edges, classes, eps, eps_max, title))
            subprocess.run(["rsvg-convert", svg_path, "-o", png_path], check=True)
            os.remove(svg_path)
        print(f"wrote {args.frames} frames to {args.animate}")
        if args.anim_out:
            subprocess.run(
                ["tools/blender.sh", "encode", args.animate, args.anim_out, "--fps", str(args.fps)],
                check=True,
            )


if __name__ == "__main__":
    main()
