"""hearsay.viz — PNG output (stdlib zlib writer, numpy raster) and ANSI helpers."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------


def write_png(path: str | Path, rgb: np.ndarray) -> None:
    """rgb: (H, W, 3) uint8."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))
    comp = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(png)


# ---------------------------------------------------------------------------
# Colour maps
# ---------------------------------------------------------------------------

_MAGMA = np.array(
    [
        (0, 0, 4),
        (28, 16, 68),
        (79, 18, 123),
        (129, 37, 129),
        (181, 54, 122),
        (229, 80, 100),
        (251, 135, 97),
        (254, 194, 135),
        (252, 253, 191),
    ],
    dtype=np.float64,
)
_VIRIDIS = np.array(
    [
        (68, 1, 84),
        (72, 40, 120),
        (62, 74, 137),
        (49, 104, 142),
        (38, 130, 142),
        (31, 158, 137),
        (53, 183, 121),
        (109, 205, 89),
        (180, 222, 44),
        (253, 231, 37),
    ],
    dtype=np.float64,
)


def cmap(t: np.ndarray, name: str = "magma") -> np.ndarray:
    """t in [0,1] any shape -> uint8 rgb (..., 3)."""
    table = _MAGMA if name == "magma" else _VIRIDIS
    t = np.clip(np.nan_to_num(t), 0.0, 1.0)
    pos = t * (len(table) - 1)
    i = np.floor(pos).astype(int)
    i = np.clip(i, 0, len(table) - 2)
    f = (pos - i)[..., None]
    rgb = table[i] * (1 - f) + table[i + 1] * f
    return rgb.astype(np.uint8)


def upscale(img: np.ndarray, sy: int, sx: int) -> np.ndarray:
    return np.repeat(np.repeat(img, sy, axis=0), sx, axis=1)


def normalise(a: np.ndarray) -> np.ndarray:
    lo, hi = float(a.min()), float(a.max())
    return (a - lo) / (hi - lo + 1e-12)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def rf_gallery(
    rfs: np.ndarray, cols: int = 10, cell: int = 4, gap: int = 2, order: np.ndarray | None = None
) -> np.ndarray:
    """rfs (N, D, n_in) -> tiled image. Each tile: rows = fiber (low freq at
    bottom), columns = delay (most recent at right). One tile per neuron."""
    N, D, n_in = rfs.shape
    order = np.arange(N) if order is None else order
    rows = int(np.ceil(len(order) / cols))
    tile_h, tile_w = n_in * cell // 2, D * cell * 2
    H = rows * (tile_h + gap) + gap
    W = cols * (tile_w + gap) + gap
    img = np.full((H, W, 3), 18, dtype=np.uint8)
    for k, n in enumerate(order):
        r, c = divmod(k, cols)
        patch = rfs[n]  # (D, n_in)
        patch = normalise(patch).T[::-1]  # (n_in, D), low freq at bottom
        tile = upscale(cmap(patch, "magma"), cell // 2, cell * 2)
        y0 = gap + r * (tile_h + gap)
        x0 = gap + c * (tile_w + gap)
        img[y0 : y0 + tile_h, x0 : x0 + tile_w] = tile
    return img


def raster_image(
    nerve: np.ndarray, cortex: np.ndarray, cochleagram: np.ndarray, scale: int = 2
) -> np.ndarray:
    """Stack cochleagram (top), nerve spikes, cortex spikes (bottom) over time."""
    T = cochleagram.shape[1]
    coch = upscale(cmap(normalise(cochleagram)[::-1], "magma"), 3, scale)
    nerve_img = np.full((nerve.shape[0], T, 3), 12, dtype=np.uint8)
    nerve_img[nerve[::-1]] = (255, 200, 90)
    nerve_img = upscale(nerve_img, 2, scale)
    ctx_img = np.full((cortex.shape[0], T, 3), 12, dtype=np.uint8)
    ctx_img[cortex] = (120, 220, 255)
    ctx_img = upscale(ctx_img, 2, scale)
    sep = np.full((3, T * scale, 3), 60, dtype=np.uint8)
    return np.concatenate([coch, sep, nerve_img, sep, ctx_img], axis=0)


def matrix_image(m: np.ndarray, cell: int = 14, name: str = "viridis") -> np.ndarray:
    m = np.asarray(m, dtype=np.float64)
    row_sum = m.sum(axis=1, keepdims=True) + 1e-9
    return upscale(cmap(m / row_sum, name), cell, cell)


def curve_image(
    xs: np.ndarray,
    series: dict[str, np.ndarray],
    width: int = 480,
    height: int = 240,
    ylim: tuple[float, float] = (0.0, 1.0),
) -> np.ndarray:
    """Tiny line plot: several accuracy curves over xs. Colours cycle."""
    img = np.full((height, width, 3), 16, dtype=np.uint8)
    pad = 24
    colours = [(255, 120, 90), (120, 220, 255), (255, 220, 90), (160, 255, 140), (220, 140, 255)]
    # grid
    for gy in np.linspace(ylim[0], ylim[1], 5):
        y = int(height - pad - (gy - ylim[0]) / (ylim[1] - ylim[0]) * (height - 2 * pad))
        img[y, pad:-pad] = (50, 50, 50)
    x_lo, x_hi = float(xs.min()), float(xs.max())
    for k, (_name, ys) in enumerate(series.items()):
        col = colours[k % len(colours)]
        pts = []
        for x, y in zip(xs, ys, strict=True):
            px = int(pad + (x - x_lo) / (x_hi - x_lo + 1e-9) * (width - 2 * pad))
            py = int(height - pad - (y - ylim[0]) / (ylim[1] - ylim[0]) * (height - 2 * pad))
            pts.append((px, py))
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:], strict=True):
            n = max(abs(x1 - x0), abs(y1 - y0), 1)
            for i in range(n + 1):
                x = x0 + (x1 - x0) * i // n
                y = y0 + (y1 - y0) * i // n
                img[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = col
        # legend swatch
        img[8 + k * 8 : 12 + k * 8, 8:20] = col
    return img


# ---------------------------------------------------------------------------
# ANSI (for the live view)
# ---------------------------------------------------------------------------


def ansi_heat_row(values: np.ndarray, name: str = "magma") -> str:
    rgb = cmap(values, name)
    return "".join(f"\x1b[48;2;{r};{g};{b}m " for r, g, b in rgb) + "\x1b[0m"


def ansi_rgb(text: str, rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m"


def ansi_to_html(text: str, title: str = "hearsay") -> str:
    """Convert our (truecolor-only) ANSI frame to a standalone HTML page."""
    import html
    import re

    out = [
        '<pre style="background:#0e0e0e;color:#d0d0d0;font:14px/1.15 monospace;padding:12px;margin:0;display:inline-block">'
    ]
    fg = bg = None
    pos = 0
    for m in re.finditer(r"\x1b\[([0-9;]*)m", text):
        seg = text[pos : m.start()]
        if seg:
            style = []
            if fg:
                style.append(f"color:rgb({fg})")
            if bg:
                style.append(f"background:rgb({bg})")
            out.append(
                f'<span style="{";".join(style)}">{html.escape(seg)}</span>'
                if style
                else html.escape(seg)
            )
        pos = m.end()
        code = m.group(1)
        if code in ("", "0"):
            fg = bg = None
        elif code.startswith("38;2;"):
            fg = code[5:].replace(";", ",")
        elif code.startswith("48;2;"):
            bg = code[5:].replace(";", ",")
    out.append(html.escape(text[pos:]))
    out.append("</pre>")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title></head><body style='margin:0;background:#0e0e0e'>{''.join(out)}</body></html>"


def html_screenshot(html_path: Path, png_path: Path, width: int = 900, height: int = 700) -> bool:
    """Render an HTML file to PNG with headless chromium, if available."""
    import shutil
    import subprocess

    exe = (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome-stable")
    )
    if not exe:
        return False
    subprocess.run(
        [
            exe,
            "--headless=new",
            "--hide-scrollbars",
            f"--window-size={width},{height}",
            f"--screenshot={png_path}",
            f"file://{html_path.resolve()}",
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    return png_path.exists()
