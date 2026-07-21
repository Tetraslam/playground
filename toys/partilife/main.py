"""partilife — particle life: a system where the rules themselves are the genome.

N particles, K colors, one (K×K) inter-color attraction matrix A. Each color
exerts a signed force on every other color: positive A[c_i][c_j] pulls directed
particles together, negative pushes them apart. The force falls off in a smooth
sin bump over a distance beta, plus a sharp soft-repulsion at very short range
so particles never collapse onto each other. Friction damps the system into a
non-equilibrium steady state — and that steady state is *wildly* variable.

The matrix IS the genome. Change one entry by 0.2 and the ecology flips:
cells with rotating nuclei, chains, oscillators, swarming ropes, layered
crystals, traveling bands. Random matrices almost always yield *something*
interesting; the fun is hunting for the matrix that surprises you.

Run:
    uv run python toys/partilife/main.py                    # interactive terminal sim
    uv run python toys/partilife/main.py --save-frames out  # headless: dump PNG frames
    uv run python toys/partilife/main.py --encode examples  # encode saved frames -> webp/mp4
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
import termios
import tty
import zlib
from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# world constants
# ---------------------------------------------------------------------------

WORLD = 1.0  # torus side — unit square; positions live in [0, WORLD)
BETA = 0.18  # interaction range — about 1/5 of the world
R_REPEL = 0.012  # hard soft-repulsion radius — prevents particle overlap
REPEL_STRENGTH = 1.4  # how strongly the short-range kernel pushes apart
DT = 0.005  # integration timestep
FRICTION = 0.05  # exponential damping per step (1 - FRICTION multiplicative)
MAX_SPEED = 1.3  # velocity cap — keeps the system stable on bad matrices
K_COLORS = 6  # number of distinct colors / matrix dimension

# palette: 6 high-contrast hues, picked to read well on a dark canvas
PALETTE = np.array(
    [
        [232, 76, 79],  # crimson
        [82, 196, 105],  # spring green
        [84, 132, 232],  # cobalt
        [64, 196, 220],  # cyan
        [221, 100, 221],  # magenta
        [240, 196, 70],  # gold
    ],
    dtype=np.uint8,
)


# ---------------------------------------------------------------------------
# world state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class World:
    x: np.ndarray  # (N,) horizontal positions in [0, WORLD)
    y: np.ndarray  # (N,) vertical positions
    vx: np.ndarray  # (N,)
    vy: np.ndarray  # (N,)
    colors: np.ndarray  # (N,) int in [0, K)
    matrix: np.ndarray  # (K, K) — the genome
    rng: np.random.Generator


def random_world(
    n: int, k: int, rng: np.random.Generator, matrix: np.ndarray | None = None
) -> World:
    """Spawn n particles of k colors, uniformly placed, with zero velocity."""
    cols = rng.integers(0, k, size=n)
    if matrix is None:
        matrix = rng.uniform(-1.0, 1.0, size=(k, k))
    return World(
        x=rng.uniform(0, WORLD, size=n),
        y=rng.uniform(0, WORLD, size=n),
        vx=np.zeros(n),
        vy=np.zeros(n),
        colors=cols,
        matrix=matrix.astype(np.float64),
        rng=rng,
    )


# ---------------------------------------------------------------------------
# physics — one vectorized step
# ---------------------------------------------------------------------------


def step(w: World) -> None:
    """Advance the world by DT. O(N²) pairwise; ~30 fps at N=1800 on a laptop."""
    A = w.matrix
    cols = w.colors

    # pairwise displacement with minimum-image toroidal wrap
    dx = w.x[None, :] - w.x[:, None]  # (N, N) — vector from i to j
    dy = w.y[None, :] - w.y[:, None]
    dx -= WORLD * np.round(dx / WORLD)  # torus minimum image
    dy -= WORLD * np.round(dy / WORLD)
    r2 = dx * dx + dy * dy

    in_range = r2 < BETA * BETA
    r = np.sqrt(np.maximum(r2, 1e-12))

    # smooth attraction kernel: sin bump, 0 at 0, peak at BETA/2, 0 at BETA.
    sense = r / BETA
    attr = np.where(in_range, np.sin(np.pi * sense), 0.0)

    # sharp repulsion inside R_REPEL prevents particles sharing a point.
    repel = np.where(r < R_REPEL, (1.0 - r / R_REPEL), 0.0)

    # per-pair force amplitude: signed attraction minus always-on soft repel.
    # A[c_i, c_j] is the genome entry governing how color i feels color j.
    Amat = A[cols[:, None], cols[None, :]]
    fmag = Amat * attr - REPEL_STRENGTH * repel

    # zero the diagonal (a particle does not exert force on itself).
    fmag = np.where(r2 > 1e-10, fmag, 0.0)

    # unit direction from i to j; force pulls i toward j when amplitude > 0.
    inv_r = 1.0 / r
    fx = (fmag * dx * inv_r).sum(axis=1)
    fy = (fmag * dy * inv_r).sum(axis=1)

    # semi-implicit Euler with linear friction
    w.vx = (w.vx + DT * fx) * (1.0 - FRICTION)
    w.vy = (w.vy + DT * fy) * (1.0 - FRICTION)

    # cap speed to keep the sim stable on pathological matrices
    speed = np.sqrt(w.vx * w.vx + w.vy * w.vy)
    over = speed > MAX_SPEED
    if np.any(over):
        scale = MAX_SPEED / np.maximum(speed, 1e-9)
        w.vx = np.where(over, w.vx * scale, w.vx)
        w.vy = np.where(over, w.vy * scale, w.vy)

    w.x = (w.x + DT * w.vx) % WORLD
    w.y = (w.y + DT * w.vy) % WORLD


# ---------------------------------------------------------------------------
# matrix I/O — genomes must be reproducible
# ---------------------------------------------------------------------------


def describe_matrix(m: np.ndarray) -> str:
    """Compact single-line genome signature for filenames and logs."""
    flat = m.flatten()
    return "m" + "_".join(f"{v:+.2f}" for v in flat).replace("+", "p").replace("-", "n")


def parse_matrix(sig: str) -> np.ndarray:
    """Inverse of describe_matrix."""
    body = sig.removeprefix("m")
    parts = body.split("_")
    vals = [float(p.replace("p", "+").replace("n", "-")) for p in parts]
    return np.array(vals, dtype=np.float64).reshape(K_COLORS, K_COLORS)


# ---------------------------------------------------------------------------
# PNG writer (pure stdlib) — cribbed from primordia, same approach
# ---------------------------------------------------------------------------


def write_png(path: str, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    raw = bytearray()
    for row in rgb:
        raw.append(0)  # filter type 0 per scanline
        raw.extend(row.tobytes())
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------

TERM_W = 90
TERM_H = 48


def render_terminal(w: World) -> str:
    """Coarse ASCII grid: each cell is the majority color seen there, colored."""
    grid = np.full((TERM_H, TERM_W), -1, dtype=np.int8)
    counts = np.zeros((TERM_H, TERM_W), dtype=np.int32)
    tw = WORLD / TERM_W
    th = WORLD / TERM_H
    tx = (w.x / tw).astype(np.int32) % TERM_W
    ty = (w.y / th).astype(np.int32) % TERM_H
    for i in range(len(w.x)):
        gx, gy = tx[i], ty[i]
        counts[gy, gx] += 1
        grid[gy, gx] = w.colors[i]

    # ANSI 24-bit color glyphs. dense cells glow, empty is dark space.
    out = []
    palette_glyph = ".o+:*O#@"  # intensity by count, capped
    for gy in range(TERM_H):
        line = []
        for gx in range(TERM_W):
            c = counts[gy, gx]
            if c == 0:
                line.append("\x1b[38;2;18;18;26m.")
                continue
            col = PALETTE[grid[gy, gx]]
            glyph = palette_glyph[min(c - 1, len(palette_glyph) - 1)]
            line.append(f"\x1b[38;2;{col[0]};{col[1]};{col[2]}m{glyph}")
        out.append("".join(line))
    return "\n".join(out) + "\x1b[0m"


CANVAS = 720  # output PNG side in pixels


def render_png(world: World, path: str) -> None:
    """High-res still: each particle is a glowing dot on a near-black canvas."""
    side = CANVAS
    rgb = np.zeros((side, side, 3), dtype=np.uint8)
    rgb[:] = 10  # near-black background

    # world coords -> pixel coords (torus wraps anyway, but keep tidy)
    px = (world.x / WORLD * side).astype(np.int32) % side  # column
    py = (world.y / WORLD * side).astype(np.int32) % side  # row
    col = PALETTE[world.colors]  # (N,3)

    def stamp(ox: int, oy: int, scale: float) -> None:
        rows = (py + oy) % side  # y
        cols = (px + ox) % side  # x
        rgb[rows, cols] = np.maximum(rgb[rows, cols], (col * scale).astype(np.uint8))

    # additive splat: core at full brightness, halos fading outward
    stamp(0, 0, 1.00)
    for off in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        stamp(off[0], off[1], 0.70)
    for off in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
        stamp(off[0], off[1], 0.40)
    for off in [(2, 0), (-2, 0), (0, 2), (0, -2)]:
        stamp(off[0], off[1], 0.25)

    write_png(path, rgb)


# ---------------------------------------------------------------------------
# frame encoding — turn a PNG sequence into a committable webp / mp4 / strip
# ---------------------------------------------------------------------------


def encode_frames(frames_dir: str, outbase: str, fps: int = 30) -> None:
    """ffmpeg PNGs -> webp (github-inline) + mp4 (local); magick -> filmstrip."""
    first = os.path.join(frames_dir, "%05d.png")
    webp = f"{outbase}.webp"
    mp4 = f"{outbase}.mp4"
    strip = f"{outbase}_strip.png"
    n_frames = len([f for f in os.listdir(frames_dir) if f.endswith(".png")])
    if n_frames == 0:
        print(f"no PNG frames in {frames_dir}", file=sys.stderr)
        sys.exit(1)
    # animated webp — committable, plays inline in READMEs
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            first,
            "-loop",
            "0",
            "-c:v",
            "libwebp",
            "-preset",
            "default",
            "-vf",
            "scale=720:720",
            "-compression_level",
            "6",
            webp,
        ],
        check=True,
    )
    # h264 mp4 for local viewing (stays in renders/)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            first,
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=720:720",
            mp4,
        ],
        check=True,
    )
    # 6-frame filmstrip, committable, one image summarizing the timeline
    step_idx = max(1, (n_frames - 1) // 5)
    picks = sorted(os.listdir(frames_dir))
    picks = [picks[min(i * step_idx, n_frames - 1)] for i in range(6)]
    inputs = []
    for p in picks:
        inputs.extend([os.path.join(frames_dir, p), "-label", os.path.splitext(p)[0]])
    subprocess.run(
        [
            "magick",
            "montage",
            "-tile",
            "6x1",
            "-geometry",
            "+4+4",
            "-background",
            "#0a0a0e",
            *inputs,
            strip,
        ],
        check=True,
    )
    print(f"wrote {webp}\nwrote {mp4}\nwrote {strip}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="particle life — rules are the genome")
    ap.add_argument("--n", type=int, default=1800, help="particles")
    ap.add_argument("--seed", type=int, default=None, help="seed for particle placement")
    ap.add_argument(
        "--matrix",
        type=str,
        default=None,
        help="genome signature (output of describe_matrix) or 'random'",
    )
    ap.add_argument(
        "--mutate", type=float, default=0.0, help="add gaussian noise of this sigma to the matrix"
    )
    ap.add_argument(
        "--save-frames",
        type=str,
        default=None,
        help="if set, run headless and dump PNGs to this dir",
    )
    ap.add_argument("--steps", type=int, default=2000, help="headless steps to simulate")
    ap.add_argument("--frame-every", type=int, default=20, help="save a frame every N steps")
    ap.add_argument(
        "--encode",
        type=str,
        default=None,
        help="encode saved frames at this path (drop the extension)",
    )
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    # build the matrix
    matrix = None
    if args.matrix and args.matrix != "random":
        matrix = parse_matrix(args.matrix)
    elif args.matrix is None:
        matrix = rng.uniform(-1.0, 1.0, size=(K_COLORS, K_COLORS))
    if args.mutate and matrix is not None:
        matrix = matrix + rng.normal(0, args.mutate, size=matrix.shape)
        matrix = np.clip(matrix, -1.0, 1.0)

    w = random_world(args.n, K_COLORS, rng, matrix)
    sig = describe_matrix(w.matrix)
    print(f"# genome signature: {sig}", file=sys.stderr)

    if args.save_frames:
        os.makedirs(args.save_frames, exist_ok=True)
        for i in range(args.steps + 1):
            if i % args.frame_every == 0:
                render_png(w, os.path.join(args.save_frames, f"{i:05d}.png"))
            step(w)
        print(
            f"# saved {args.steps // args.frame_every + 1} frames -> {args.save_frames}",
            file=sys.stderr,
        )
        if args.encode:
            encode_frames(args.save_frames, args.encode)
        return

    # interactive: cycle the matrix live, watch the world morph
    print("\x1b[2J\x1b[H", end="")
    print(render_terminal(w))
    print("press [r] new matrix  [m] mutate  [q] quit", end="", flush=True)
    fd = sys.stdin.fileno()
    if not sys.stdin.isatty():
        print(
            "\n# no tty; run without redirection for the live sim, "
            "or use --save-frames for a headless render.",
            file=sys.stderr,
        )
        return
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            step(w)
            sys.stdout.write("\x1b[H")
            sys.stdout.write(render_terminal(w))
            sys.stdout.write(
                f"\n\x1b[2K\nsignature: {sig}    N={args.n}    [r]mtx [m]mutate [q]quit\x1b[0m"
            )
            sys.stdout.flush()
            # poll for a keystroke without blocking the sim
            import select

            r, _, _ = select.select([sys.stdin], [], [], 0.0)
            if r:
                ch = sys.stdin.read(1)
                if ch == "q":
                    break
                elif ch == "r":
                    w.matrix = rng.uniform(-1.0, 1.0, size=(K_COLORS, K_COLORS))
                    sig = describe_matrix(w.matrix)
                elif ch == "m":
                    w.matrix = np.clip(
                        w.matrix + rng.normal(0, 0.3, size=w.matrix.shape),
                        -1.0,
                        1.0,
                    )
                    sig = describe_matrix(w.matrix)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
