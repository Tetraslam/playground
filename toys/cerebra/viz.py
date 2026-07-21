"""cerebra.viz — PNG writer, terminal ASCII, learning curves, behavior strips.

Pure stdlib + numpy. Hand-rolled PNG so no PIL dep. Hand-rolled line plot for
the learning curve so no matplotlib dep. Reads arrays straight out of World.
"""

from __future__ import annotations

import zlib

import numpy as np

# share world constants — imported lazily so viz stays decoupled from world for
# the standalone PNG writer, but uses the same geometry for live rendering.
from world import WORLD, WORLD_H

# ---------------------------------------------------------------------------
# PNG (pure stdlib — same shape as primordia's writer)
# ---------------------------------------------------------------------------


def write_png(path: str, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    raw = bytearray()
    for row in rgb:
        raw.append(0)
        raw.extend(row.tobytes())
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big")
            + tag + data
            + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big")
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


# ---------------------------------------------------------------------------
# world render — top-down view of a single env
# ---------------------------------------------------------------------------

TERM_W = 100
TERM_H = 50
PX = 6  # downsampling cell -> this many pixels per terminal cell


def render_world_rgb(world, env_idx: int) -> np.ndarray:
    """Render a single env's top-down world. Returns (H, W, 3) uint8."""
    rgb = np.zeros((TERM_H * PX, TERM_W * PX, 3), dtype=np.uint8)
    rgb[:] = 8  # near-black background

    # plants — color greenish by plant energy
    G0 = world.gw
    GY = world.gh
    cells = world.plants[env_idx]
    for gy in range(GY):
        for gx in range(G0):
            e = cells[gy, gx]
            if e > 0:
                tx = int(gx / G0 * TERM_W) * PX
                ty = int(gy / GY * TERM_H) * PX
                t = min(1.0, e / 8.0)
                rgb[ty:ty + PX, tx:tx + PX, 1] = int(30 + 110 * t)
                rgb[ty:ty + PX, tx:tx + PX, 2] = int(20 + 40 * t)

    # prey — small bright cyan dots
    pp = world.ppos[env_idx]
    pe = world.pene[env_idx]
    pa = world.palive[env_idx]
    for i in range(pp.shape[0]):
        if not pa[i]:
            continue
        tx = int(pp[i, 0] / WORLD * TERM_W) * PX
        ty = int(pp[i, 1] / WORLD_H * TERM_H) * PX
        e_t = min(1.0, pe[i] / 100.0)
        for dy in range(PX):
            for dx in range(PX):
                if dx * dx + dy * dy <= PX * PX / 2:
                    if 0 <= tx + dx < rgb.shape[1] and 0 <= ty + dy < rgb.shape[0]:
                        rgb[ty + dy, tx + dx, 0] = 40
                        rgb[ty + dy, tx + dx, 1] = 200
                        rgb[ty + dy, tx + dx, 2] = int(140 + 80 * e_t)

    # predators — bright red, with a small heading arrow
    qp = world.qpos[env_idx]
    qe = world.qene[env_idx]
    qa = world.qalive[env_idx]
    qh = world.qhead[env_idx]
    for i in range(qp.shape[0]):
        if not qa[i]:
            continue
        # disk for body
        cx = int(qp[i, 0] / WORLD * TERM_W) * PX + PX // 2
        cy = int(qp[i, 1] / WORLD_H * TERM_H) * PX + PX // 2
        e_t = min(1.0, qe[i] / 120.0)
        r0 = int(PX * 0.6)
        for dy in range(-r0, r0 + 1):
            for dx in range(-r0, r0 + 1):
                if dx * dx + dy * dy <= r0 * r0:
                    if 0 <= cx + dx < rgb.shape[1] and 0 <= cy + dy < rgb.shape[0]:
                        rgb[cy + dy, cx + dx, 0] = 220
                        rgb[cy + dy, cx + dx, 1] = int(60 + 60 * e_t)
                        rgb[cy + dy, cx + dx, 2] = 60
        # heading indicator: 1-pixel line forward
        for r in range(r0, r0 + 4):
            x = int(cx + r * np.cos(qh[i]))
            y = int(cy + r * np.sin(qh[i]))
            if 0 <= x < rgb.shape[1] and 0 <= y < rgb.shape[0]:
                rgb[y, x, 0] = 255
                rgb[y, x, 1] = 200
                rgb[y, x, 2] = 180
    return rgb


def render_world_png(world, env_idx: int, path: str) -> None:
    write_png(path, render_world_rgb(world, env_idx))


# ---------------------------------------------------------------------------
# terminal ASCII (live)
# ---------------------------------------------------------------------------

def render_terminal(world, env_idx: int = 0, stats: dict | None = None) -> str:
    grid = [[" "] * TERM_W for _ in range(TERM_H)]
    cells = world.plants[env_idx]
    for gy in range(world.gh):
        for gx in range(world.gw):
            if cells[gy, gx] > 2.0:
                tx = int(gx / world.gw * TERM_W)
                ty = int(gy / world.gh * TERM_H)
                if grid[ty][tx] == " ":
                    grid[ty][tx] = ","
    pp = world.ppos[env_idx]
    pa = world.palive[env_idx]
    for i in range(pp.shape[0]):
        if not pa[i]:
            continue
        tx = int(pp[i, 0] / WORLD * TERM_W)
        ty = int(pp[i, 1] / WORLD_H * TERM_H)
        if 0 <= tx < TERM_W and 0 <= ty < TERM_H:
            # heading shown by arrow-ish char
            grid[ty][tx] = "·"
    qp = world.qpos[env_idx]
    qa = world.qalive[env_idx]
    for i in range(qp.shape[0]):
        if not qa[i]:
            continue
        tx = int(qp[i, 0] / WORLD * TERM_W)
        ty = int(qp[i, 1] / WORLD_H * TERM_H)
        if 0 <= tx < TERM_W and 0 <= ty < TERM_H:
            grid[ty][tx] = "▲"
    body = "\n".join("".join(r) for r in grid)
    if stats is None:
        stats = {}
    bar = (
        f"iter {stats.get('iter', 0):4d} | step {world.step_count:3d} | "
        f"alive prey {int(pa.sum()):3d}/{pp.shape[0]} "
        f"pred {int((qa).sum()):2d}/{qp.shape[0]}  "
        f"prey R {stats.get('rp', 0):6.2f}  pred R {stats.get('rq', 0):6.2f}"
    )
    legend = "prey ·   pred ▲   plant ,     [q]uit    [+/-]speed    [r]oll-snapshot"
    return bar + "\n" + legend + "\n" + body


# ---------------------------------------------------------------------------
# learning curve plot (hand-rolled)
# ---------------------------------------------------------------------------

CURVE_W = 800
CURVE_H = 320
PADDING = 60


def render_curve_png(
    history: dict, path: str, title: str = "cerebra — learning curve"
) -> None:
    """history = {'iter': [...], 'rp_mean': [...], 'rq_mean': [...],
                  'rp_max': [...], 'rq_max': [...]}"""
    rgb = np.full((CURVE_H, CURVE_W, 3), 18, dtype=np.uint8)
    plot_w = CURVE_W - 2 * PADDING
    plot_h = CURVE_H - 2 * PADDING

    def draw_pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < CURVE_W and 0 <= y < CURVE_H:
            rgb[y, x, 0] = color[0]
            rgb[y, x, 1] = color[1]
            rgb[y, x, 2] = color[2]

    def draw_line(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        # Bresenham
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            # fat pencil — 1 pixel wide + a neighbor
            draw_pixel(x0, y0, color)
            if 0 <= y0 + 1 < CURVE_H:
                draw_pixel(x0, y0 + 1, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    # axis frame
    draw_line(PADDING, PADDING, PADDING, CURVE_H - PADDING, (80, 80, 80))
    draw_line(PADDING, CURVE_H - PADDING, CURVE_W - PADDING, CURVE_H - PADDING, (80, 80, 80))

    iters = history["iter"]
    if not iters:
        write_png(path, rgb)
        return

    # series — (key, color, name)
    series = [
        ("rp_mean", (90, 200, 160), "prey"),
        ("rq_mean", (240, 90, 90), "pred"),
        ("rp_max",  (40, 100, 80),  "prey max"),
        ("rq_max",  (120, 40, 40),  "pred max"),
    ]
    all_vals = []
    for k, _, _ in series:
        all_vals.extend(history[k])
    if not all_vals:
        write_png(path, rgb)
        return
    y_min = min(0.0, min(all_vals))
    y_max = max(0.5, max(all_vals))
    x_min = iters[0]
    x_max = max(iters[-1], 1)

    def map_pt(x, y):
        px = int(PADDING + (x - x_min) / (x_max - x_min + 1e-9) * plot_w)
        py = int(CURVE_H - PADDING - (y - y_min) / (y_max - y_min + 1e-9) * plot_h)
        return px, py

    # draw max-series faintly first, then mean-series bold on top
    faint = [s for s in series if "max" in s[0]]
    bold = [s for s in series if "max" not in s[0]]
    for k, color, _ in faint:
        vals = history[k]
        prev = None
        for x, y in zip(iters, vals, strict=False):
            pt = map_pt(x, y)
            if prev is not None:
                draw_line(prev[0], prev[1], pt[0], pt[1], color)
            prev = pt
    for k, color, _ in bold:
        vals = history[k]
        prev = None
        for x, y in zip(iters, vals, strict=False):
            pt = map_pt(x, y)
            if prev is not None:
                draw_line(prev[0], prev[1], pt[0], pt[1], color)
            prev = pt

    # legend dots
    lx, ly = PADDING + 10, PADDING + 10
    for _, color, _ in bold:
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx * dx + dy * dy <= 9:
                    draw_pixel(lx + dx, ly + dy, color)
        lx += 80
    write_png(path, rgb)


# ---------------------------------------------------------------------------
# behavior strip — several world snapshots side by side with iteration labels
# ---------------------------------------------------------------------------

STRIP_PAD = 16
STRIP_LABEL_H = 28


def compose_strip(
    frames: list[tuple[int, np.ndarray]], out_path: str,
    label: str = "cerebra",
) -> None:
    """Lay out (iter, rgb) frames horizontally, and add a text label below
    each saying "iter N". Then write the composite PNG."""
    if not frames:
        return
    h, w, _ = frames[0][1].shape
    n = len(frames)
    total_w = n * w + (n + 1) * STRIP_PAD
    total_h = h + STRIP_LABEL_H + 2 * STRIP_PAD
    rgb = np.zeros((total_h, total_w, 3), dtype=np.uint8)
    rgb[:] = 20
    for i, (it, frame) in enumerate(frames):
        x0 = STRIP_PAD + i * (w + STRIP_PAD)
        y0 = STRIP_PAD
        rgb[y0:y0 + h, x0:x0 + w] = frame
        # brighten frame border
        for k in range(h):
            for c in range(3):
                v1 = int(rgb[y0 + k, x0, c]) + 30
                v2 = int(rgb[y0 + k, x0 + w - 1, c]) + 30
                rgb[y0 + k, x0, c] = min(255, v1)
                rgb[y0 + k, x0 + w - 1, c] = min(255, v2)
        for k in range(w):
            for c in range(3):
                v1 = int(rgb[y0, x0 + k, c]) + 30
                v2 = int(rgb[y0 + h - 1, x0 + k, c]) + 30
                rgb[y0, x0 + k, c] = min(255, v1)
                rgb[y0 + h - 1, x0 + k, c] = min(255, v2)
        # label "iter N" — drawn with simple block letters
        text = f"iter {it}"
        _draw_text(rgb, text, x0 + 2, y0 + h + 6, color=(220, 220, 220))
    write_png(out_path, rgb)


# very small 5x7 bitmap font — uppercase, digits, space only, just for labels
_FONT: dict[str, list[str]] = {
    "0": ["11111", "10001", "10011", "10101", "11001", "10001", "11111"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["11110", "00001", "00001", "01110", "10000", "10000", "11111"],
    "3": ["11111", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["10010", "10010", "10010", "11111", "00010", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    "i": ["00100", "00100", "00000", "00100", "00100", "00100", "01100"],
    "t": ["00100", "00100", "00100", "11111", "00100", "00100", "00100"],
    "e": ["00000", "01110", "10001", "11111", "10000", "10001", "01110"],
    "r": ["00000", "10110", "11001", "10000", "10000", "10000", "10000"],
}


def _draw_text(
    rgb: np.ndarray, text: str, x: int, y: int,
    color: tuple[int, int, int] = (200, 200, 200),
) -> None:
    scale = 2
    cx = x
    for ch in text:
        glyph = _FONT.get(ch, _FONT[" "])
        for row_i, row in enumerate(glyph):
            for col_i, bit in enumerate(row):
                if bit == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            xx, yy = cx + col_i * scale + dx, y + row_i * scale + dy
                            if 0 <= xx < rgb.shape[1] and 0 <= yy < rgb.shape[0]:
                                rgb[yy, xx, 0] = color[0]
                                rgb[yy, xx, 1] = color[1]
                                rgb[yy, xx, 2] = color[2]
        cx += 6 * scale
