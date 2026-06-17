"""primordia — a coevolutionary ecosystem with tiny neural-net brains.

Prey eat plants. Predators eat prey. Every critter's behavior is driven by a
small feedforward net whose weights ARE its genome; offspring inherit a mutated
copy. No behavior is hand-authored — foraging, fleeing, hunting, and crowding
all have to emerge from selection on the weights.

It runs live in the terminal (ASCII grid + rolling stats) and you can perturb
it mid-flight with single-key stdin commands:

    f   drop a burst of food
    p   spawn predators
    P   spawn prey
    m   cycle mutation rate (low -> med -> high -> low)
    k   cull half the population (both species)
    +   speed up (fewer renders per step)
    -   slow down
    q   quit

Run:
    uv run python toys/primordia/main.py
    uv run python toys/primordia/main.py --prey 200 --preds 30 --steps 4000 \
        --save-frames examples/run --frame-every 100
"""

from __future__ import annotations

import argparse
import math
import os
import select
import sys
import termios
import tty
import zlib
from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# world constants
# ---------------------------------------------------------------------------

WORLD = 140.0  # width  (continuous torus)
WORLD_H = 90.0  # height
SENSE_R = 14.0  # how far critters can sense
EAT_R = 0.8  # contact radius for eating — must nearly touch
PLANT_E = 12.0  # energy in a fresh plant

PREY_META = 0.014  # per-step metabolism, prey
PRED_META = 0.095  # predators burn hot — they starve without regular kills
MOVE_COST = 0.016  # per unit speed per step — punishes thrashing
AGE_COST = 0.0006  # gentle senescence
REPRO_THRESHOLD_PREY = 95.0
REPRO_THRESHOLD_PRED = 150.0
REPRO_CHILD_FRAC = 0.45  # child gets this fraction of parent energy
MAX_SPEED_PREY = 2.4  # prey are faster — they can escape if they learn to flee
MAX_SPEED_PRED = 1.6  # predators slower — must ambush, not chase down
TURN_RATE = 0.9  # radians per step at full turn output
PRED_BITE = 18.0  # energy a predator gains per prey caught

# brain architecture
N_IN = 14  # 4 food + 4 conspecific + 4 threat + energy + bias
N_HID = 8
N_OUT = 2  # turn, speed
GENOME_LEN = N_IN * N_HID + N_HID + N_HID * N_OUT + N_OUT  # 138

DEFAULT_MUT = 0.08

RNG = np.random.default_rng()


# ---------------------------------------------------------------------------
# PNG writer (pure stdlib) — for example-frame snapshots
# ---------------------------------------------------------------------------


def write_png(path: str, rgb: np.ndarray) -> None:
    """Write an (H, W, 3) uint8 array to a PNG. No deps."""
    h, w, _ = rgb.shape
    raw = bytearray()
    for row in rgb:
        raw.append(0)  # filter type 0 per scanline
        raw.extend(row.tobytes())
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big")
            + tag
            + data
            + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big")
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


# ---------------------------------------------------------------------------
# population state — kept as parallel numpy arrays for vectorized stepping
# ---------------------------------------------------------------------------


@dataclass
class Pop:
    n_max: int
    pos: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    heading: np.ndarray = field(default_factory=lambda: np.empty(0))
    energy: np.ndarray = field(default_factory=lambda: np.empty(0))
    age: np.ndarray = field(default_factory=lambda: np.empty(0))
    genome: np.ndarray = field(default_factory=lambda: np.empty((0, GENOME_LEN)))
    n: int = 0

    def alloc(self, cap: int) -> None:
        self.pos = np.zeros((cap, 2))
        self.heading = np.zeros(cap)
        self.energy = np.zeros(cap)
        self.age = np.zeros(cap)
        self.genome = np.zeros((cap, GENOME_LEN))
        self.n = 0


def spawn(pop: Pop, k: int, rng: np.random.Generator, base_genome: np.ndarray | None) -> int:
    """Add k critters with random positions and (optionally mutated) genomes."""
    cap = pop.pos.shape[0]
    room = cap - pop.n
    k = min(k, room)
    if k <= 0:
        return 0
    i0 = pop.n
    sl = slice(i0, i0 + k)
    pop.pos[sl, 0] = rng.uniform(0, WORLD, k)
    pop.pos[sl, 1] = rng.uniform(0, WORLD_H, k)
    pop.heading[sl] = rng.uniform(0, 2 * math.pi, k)
    pop.energy[sl] = rng.uniform(40, 70, k)
    pop.age[sl] = 0.0
    if base_genome is None:
        pop.genome[sl] = rng.normal(0, 0.6, (k, GENOME_LEN))
    else:
        pop.genome[sl] = base_genome[None, :] + rng.normal(0, 0.6, (k, GENOME_LEN))
    pop.n += k
    return k


def active(pop: Pop):
    n = pop.n
    return pop.pos[:n], pop.heading[:n], pop.energy[:n], pop.age[:n], pop.genome[:n]


# ---------------------------------------------------------------------------
# brain — vectorized feedforward eval for a whole population
# ---------------------------------------------------------------------------


def brain(genome: np.ndarray, inputs: np.ndarray) -> np.ndarray:
    """genome: (n, GENOME_LEN), inputs: (n, N_IN) -> outputs (n, N_OUT)."""
    n = genome.shape[0]
    o = 0
    W1 = genome[:, o : o + N_IN * N_HID].reshape(n, N_IN, N_HID)
    o += N_IN * N_HID
    b1 = genome[:, o : o + N_HID]
    o += N_HID
    W2 = genome[:, o : o + N_HID * N_OUT].reshape(n, N_HID, N_OUT)
    o += N_HID * N_OUT
    b2 = genome[:, o : o + N_OUT]

    # hidden = tanh(inputs @ W1 + b1)
    h = np.tanh(np.einsum("ni,nij->nj", inputs, W1) + b1)
    out = np.tanh(np.einsum("nh,nho->no", h, W2) + b2)  # (n, 2) both in [-1,1]
    return out


# ---------------------------------------------------------------------------
# sensing — 4 directional quadrants (relative to heading) for each signal type
# ---------------------------------------------------------------------------

QUAD_BOUNDS = np.array([-math.pi, -math.pi / 2, 0, math.pi / 2, math.pi])


def sense_directional(
    my_pos: np.ndarray,
    my_head: np.ndarray,
    their_pos: np.ndarray,
    signal: np.ndarray,
) -> np.ndarray:
    """For each of n me, sum signal from all m them into 4 angular quadrants
    (back, left, front, right) relative to heading. Inverse-distance weighted.
    Returns (n, 4)."""
    n = my_pos.shape[0]
    m = their_pos.shape[0]
    if n == 0 or m == 0:
        return np.zeros((n, 4))
    # pairwise deltas on torus
    dx = their_pos[None, :, 0] - my_pos[:, None, 0]
    dy = their_pos[None, :, 1] - my_pos[:, None, 1]
    dx = (dx + WORLD / 2) % WORLD - WORLD / 2
    dy = (dy + WORLD_H / 2) % WORLD_H - WORLD_H / 2
    dist = np.sqrt(dx * dx + dy * dy) + 1e-3
    mask = dist < SENSE_R  # (n, m)
    ang = np.arctan2(dy, dx) - my_head[:, None]  # (n, m)
    ang = (ang + math.pi) % (2 * math.pi) - math.pi  # wrap to [-pi, pi]
    # bin into 4 quadrants: [-pi,-pi/2),[-pi/2,0),[0,pi/2),[pi/2,pi]
    quad = ((ang + math.pi) / (math.pi / 2)).astype(np.int64)  # 0..3
    quad = np.clip(quad, 0, 3)
    w = signal[None, :] / (1.0 + dist)  # (n, m)
    w = w * mask
    out = np.zeros((n, 4))
    for q in range(4):
        mq = quad == q
        out[:, q] = np.where(mq.any(axis=1), np.sum(w * mq, axis=1), 0.0)
    return out


# ---------------------------------------------------------------------------
# plant field — logistic regrowth, sparse cells
# ---------------------------------------------------------------------------


@dataclass
class Plants:
    cells: np.ndarray  # (GH, GW) plant energy per cell
    cell: float
    gw: int
    gh: int

    @classmethod
    def make(cls, cell: float = 4.0) -> Plants:
        gw = int(WORLD / cell)
        gh = int(WORLD_H / cell)
        cells = np.full((gh, gw), PLANT_E * 0.5)
        return cls(cells=cells, cell=cell, gw=gw, gh=gh)

    def regrow(self, rate: float) -> None:
        # linear approach to cap (refills even from fully depleted)
        self.cells += rate * (PLANT_E - self.cells) + rate * 0.3
        self.cells = np.minimum(self.cells, PLANT_E)

    def graze(self, pos: np.ndarray, eat_r: float, max_bite: float) -> np.ndarray:
        """Each critter bites plants in its cell. Returns energy gained per critter."""
        if pos.shape[0] == 0:
            return np.empty(0)
        gx = np.clip((pos[:, 0] / self.cell).astype(int), 0, self.gw - 1)
        gy = np.clip((pos[:, 1] / self.cell).astype(int), 0, self.gh - 1)
        avail = self.cells[gy, gx]
        bite = np.minimum(avail, max_bite)
        self.cells[gy, gx] -= bite
        return bite

    def density_quadrants(self, pos: np.ndarray, head: np.ndarray) -> np.ndarray:
        """4-quadrant sense of nearby plant energy, fully vectorized.
        For each critter, gather plant energy in a (2r+1)^2 cell neighborhood,
        bin by angle relative to heading, inverse-distance weight."""
        n = pos.shape[0]
        out = np.zeros((n, 4))
        if n == 0:
            return out
        cell = self.cell
        r = int(SENSE_R / cell) + 1
        # critter cell coords
        gx = (pos[:, 0] / cell).astype(int) % self.gw
        gy = (pos[:, 1] / cell).astype(int) % self.gh
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                wx = dx * cell
                wy = dy * cell
                d = math.hypot(wx, wy)
                if d > SENSE_R:
                    continue
                # gather energy at this offset for every critter (toroidal wrap)
                cx = (gx + dx) % self.gw
                cy = (gy + dy) % self.gh
                e = self.cells[cy, cx]  # (n,)
                if e.max() <= 0:
                    continue
                ang = math.atan2(wy, wx) - head  # (n,)
                ang = (ang + math.pi) % (2 * math.pi) - math.pi
                q = ((ang + math.pi) / (math.pi / 2)).astype(np.int64)
                np.clip(q, 0, 3, out=q)
                w = e / (1.0 + d)  # (n,)
                for qi in range(4):
                    m = q == qi
                    if m.any():
                        out[m, qi] += w[m]
        return out


# ---------------------------------------------------------------------------
# one simulation step
# ---------------------------------------------------------------------------


@dataclass
class World:
    prey: Pop
    preds: Pop
    plants: Plants
    step: int = 0
    mut: float = DEFAULT_MUT
    food_rate: float = 0.06
    births_prey: int = 0
    births_pred: int = 0
    deaths_prey: int = 0
    deaths_pred: int = 0
    # rolling history for stats
    hist: list = field(default_factory=list)


def step_world(w: World, rng: np.random.Generator) -> None:
    pp, ph, pe, pa, pg = active(w.prey)
    qp, qh, qe, qa, qg = active(w.preds)
    nprey = pp.shape[0]
    npred = qp.shape[0]

    # --- sensing ---
    food_s = w.plants.density_quadrants(pp, ph) if nprey else np.zeros((0, 4))
    # conspecifics (prey-prey)
    con_prey = sense_directional(pp, ph, pp, np.ones(nprey)) if nprey else np.zeros((0, 4))
    threat_prey = (
        sense_directional(pp, ph, qp, np.ones(max(npred, 1))) if nprey else np.zeros((0, 4))
    )
    # predator senses: prey as food
    food_pred = sense_directional(qp, qh, pp, np.ones(max(nprey, 1))) if npred else np.zeros((0, 4))
    con_pred = sense_directional(qp, qh, qp, np.ones(npred)) if npred else np.zeros((0, 4))
    threat_pred = np.zeros((npred, 4))  # predators have no predators

    def assemble(food, con, threat, energy):
        n = energy.shape[0]
        e_col = (energy / 100.0).reshape(n, 1)
        bias = np.ones((n, 1))
        return np.hstack([food, con, threat, e_col, bias])

    if nprey:
        inp_p = assemble(food_s, con_prey, threat_prey, pe)
        out_p = brain(pg, inp_p)
        turn_p = out_p[:, 0] * TURN_RATE
        speed_p = (out_p[:, 1] * 0.5 + 0.5) * MAX_SPEED_PREY  # map [-1,1]->[0,max]
    if npred:
        inp_q = assemble(food_pred, con_pred, threat_pred, qe)
        out_q = brain(qg, inp_q)
        turn_q = out_q[:, 0] * TURN_RATE
        speed_q = (out_q[:, 1] * 0.5 + 0.5) * MAX_SPEED_PRED

    # --- move (toroidal) ---
    if nprey:
        ph += turn_p
        ph %= 2 * math.pi
        pp[:, 0] = (pp[:, 0] + np.cos(ph) * speed_p) % WORLD
        pp[:, 1] = (pp[:, 1] + np.sin(ph) * speed_p) % WORLD_H
    if npred:
        qh += turn_q
        qh %= 2 * math.pi
        qp[:, 0] = (qp[:, 0] + np.cos(qh) * speed_q) % WORLD
        qp[:, 1] = (qp[:, 1] + np.sin(qh) * speed_q) % WORLD_H

    # --- eat ---
    if nprey:
        gained = w.plants.graze(pp, EAT_R, 3.0)
        pe += gained
    # predators eat prey on contact
    if npred and nprey:
        dx = pp[None, :, 0] - qp[:, None, 0]
        dy = pp[None, :, 1] - qp[:, None, 1]
        dx = (dx + WORLD / 2) % WORLD - WORLD / 2
        dy = (dy + WORLD_H / 2) % WORLD_H - WORLD_H / 2
        d = np.sqrt(dx * dx + dy * dy)  # (npred, nprey)
        caught = d < EAT_R  # (npred, nprey)
        # each prey caught by at most one predator: assign to nearest
        if caught.any():
            dmasked = np.where(caught, d, np.inf)
            nearest_pred = np.argmin(dmasked, axis=0)  # for each prey
            prey_caught = np.isfinite(dmasked[nearest_pred, np.arange(nprey)])
            # transfer energy
            prey_idx = np.where(prey_caught)[0]
            if prey_idx.size:
                # each predator sums energy of caught prey
                pred_idx = nearest_pred[prey_idx]
                bite = np.minimum(pe[prey_idx] * 0.8, PRED_BITE)
                pe[prey_idx] -= bite
                np.add.at(qe, pred_idx, bite)

    # --- metabolism / aging ---
    if nprey:
        pe -= PREY_META + MOVE_COST * speed_p + AGE_COST * pa
        pa += 1
    if npred:
        qe -= PRED_META + MOVE_COST * speed_q + AGE_COST * qa
        qa += 1

    # --- death ---
    if nprey:
        dead_p = (pe <= 0) | (pa > 4000)
        w.deaths_prey += int(dead_p.sum())
        keep = ~dead_p
        if not keep.all():
            _compact(w.prey, keep)
            pp, ph, pe, pa, pg = active(w.prey)
            nprey = pp.shape[0]
    if npred:
        dead_q = (qe <= 0) | (qa > 5000)
        w.deaths_pred += int(dead_q.sum())
        keep = ~dead_q
        if not keep.all():
            _compact(w.preds, keep)
            qp, qh, qe, qa, qg = active(w.preds)
            npred = qp.shape[0]

    # --- reproduction ---
    _reproduce(w.prey, REPRO_THRESHOLD_PREY, w.mut, rng, "prey", w)
    _reproduce(w.preds, REPRO_THRESHOLD_PRED, w.mut, rng, "pred", w)

    # --- plant regrowth ---
    w.plants.regrow(w.food_rate)

    w.step += 1
    w.hist.append((nprey, npred, float(w.plants.cells.sum())))


def _compact(pop: Pop, keep: np.ndarray) -> None:
    n = pop.n
    kp = keep[:n]
    new_n = int(kp.sum())
    pop.pos[:new_n] = pop.pos[:n][kp]
    pop.heading[:new_n] = pop.heading[:n][kp]
    pop.energy[:new_n] = pop.energy[:n][kp]
    pop.age[:new_n] = pop.age[:n][kp]
    pop.genome[:new_n] = pop.genome[:n][kp]
    pop.n = new_n


def _reproduce(
    pop: Pop, thresh: float, mut: float, rng: np.random.Generator, kind: str, w: World
) -> None:
    n = pop.n
    if n == 0:
        return
    ready = pop.energy[:n] > thresh
    ridx = np.where(ready)[0]
    if ridx.size == 0:
        return
    cap = pop.pos.shape[0]
    room = cap - n
    if room <= 0:
        return
    k = min(ridx.size, room)
    ridx = ridx[:k]
    parent_e = pop.energy[ridx]
    child_e = parent_e * REPRO_CHILD_FRAC
    pop.energy[ridx] -= child_e
    c0 = n
    c1 = n + k
    pop.pos[c0:c1] = pop.pos[ridx] + rng.normal(0, 1.0, (k, 2))
    pop.pos[c0:c1, 0] %= WORLD
    pop.pos[c0:c1, 1] %= WORLD_H
    pop.heading[c0:c1] = rng.uniform(0, 2 * math.pi, k)
    pop.energy[c0:c1] = child_e
    pop.age[c0:c1] = 0.0
    # mutate genome
    mut_mask = rng.random((k, GENOME_LEN)) < 0.15  # 15% of weights perturbed
    noise = rng.normal(0, mut, (k, GENOME_LEN)) * mut_mask
    pop.genome[c0:c1] = pop.genome[ridx] + noise
    pop.n = c1
    if kind == "prey":
        w.births_prey += k
    else:
        w.births_pred += k


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

TERM_W = 100
TERM_H = 40


def render_terminal(w: World) -> str:
    grid = [[" "] * TERM_W for _ in range(TERM_H)]
    # plants: sample cells into grid
    for gy in range(w.plants.gh):
        for gx in range(w.plants.gw):
            if w.plants.cells[gy, gx] > PLANT_E * 0.25:
                tx = int(gx / w.plants.gw * TERM_W)
                ty = int(gy / w.plants.gh * TERM_H)
                if grid[ty][tx] == " ":
                    grid[ty][tx] = ","
    pp, _, _, _, _ = active(w.prey)
    for x, y in pp:
        tx = int(x / WORLD * TERM_W)
        ty = int(y / WORLD_H * TERM_H)
        if 0 <= tx < TERM_W and 0 <= ty < TERM_H:
            grid[ty][tx] = "·"
    qp, _, _, _, _ = active(w.preds)
    for x, y in qp:
        tx = int(x / WORLD * TERM_W)
        ty = int(y / WORLD_H * TERM_H)
        if 0 <= tx < TERM_W and 0 <= ty < TERM_H:
            grid[ty][tx] = "*"
    lines = ["".join(r) for r in grid]
    nprey, npred, plant_e = (w.prey.n, w.preds.n, float(w.plants.cells.sum()))
    bar = (
        f"step {w.step:5d} | prey {nprey:4d} | preds {npred:4d} | "
        f"plants {plant_e:7.1f} | mut {w.mut:.3f} | "
        f"b_prey {w.births_prey} d_prey {w.deaths_prey} | "
        f"b_pred {w.births_pred} d_pred {w.deaths_pred}"
    )
    legend = (
        "prey ·   preds *   plants ,    [f]food [p]preds [P]prey [m]mut [k]cull [+/-]speed [q]uit"
    )
    return bar + "\n" + legend + "\n" + "\n".join(lines)


def render_png(w: World, path: str) -> None:
    rgb = np.zeros((TERM_H * 4, TERM_W * 4, 3), dtype=np.uint8)
    rgb[:] = 8  # near-black
    sc = 4
    # plants green
    for gy in range(w.plants.gh):
        for gx in range(w.plants.gw):
            e = w.plants.cells[gy, gx]
            if e > 0:
                t = min(1.0, e / PLANT_E)
                tx = int(gx / w.plants.gw * TERM_W) * sc
                ty = int(gy / w.plants.gh * TERM_H) * sc
                rgb[ty : ty + sc, tx : tx + sc, 1] = int(40 + 120 * t)
    pp, _, pe, _, _ = active(w.prey)
    for i in range(pp.shape[0]):
        tx = int(pp[i, 0] / WORLD * TERM_W) * sc
        ty = int(pp[i, 1] / WORLD_H * TERM_H) * sc
        e = min(1.0, pe[i] / 100.0)
        rgb[ty : ty + sc, tx : tx + sc, 1] = 200
        rgb[ty : ty + sc, tx : tx + sc, 2] = int(80 + 120 * e)
    qp, _, qe, _, _ = active(w.preds)
    for i in range(qp.shape[0]):
        tx = int(qp[i, 0] / WORLD * TERM_W) * sc
        ty = int(qp[i, 1] / WORLD_H * TERM_H) * sc
        e = min(1.0, qe[i] / 150.0)
        rgb[ty : ty + sc, tx : tx + sc, 0] = 220
        rgb[ty : ty + sc, tx : tx + sc, 1] = int(40 + 80 * e)
    write_png(path, rgb)


# ---------------------------------------------------------------------------
# non-blocking stdin (single-key commands)
# ---------------------------------------------------------------------------


class TermRaw:
    def __enter__(self):
        try:
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
        except termios.error:
            self.old = None
        return self

    def __exit__(self, *a):
        if getattr(self, "old", None) is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def read_key() -> str | None:
    try:
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if r:
            return sys.stdin.read(1)
    except (OSError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prey", type=int, default=180)
    ap.add_argument("--preds", type=int, default=15)
    ap.add_argument("--steps", type=int, default=0, help="0 = run until 'q'")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--mut", type=float, default=DEFAULT_MUT)
    ap.add_argument("--food-rate", type=float, default=0.06)
    ap.add_argument("--save-frames", type=str, default="")
    ap.add_argument("--frame-every", type=int, default=100)
    ap.add_argument("--no-tty", action="store_true", help="no live render; just run")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    world = World(
        prey=Pop(n_max=400),
        preds=Pop(n_max=150),
        plants=Plants.make(cell=6.0),
        mut=args.mut,
        food_rate=args.food_rate,
    )
    world.prey.alloc(400)
    world.preds.alloc(150)
    spawn(world.prey, args.prey, rng, None)
    spawn(world.preds, args.preds, rng, None)

    mut_cycle = [0.03, 0.08, 0.18]
    mut_i = 1

    speed = 1  # steps per render
    frame_dir = args.save_frames
    if frame_dir:
        os.makedirs(frame_dir, exist_ok=True)

    live = (not args.no_tty) and sys.stdout.isatty()
    if live:
        with TermRaw():
            _run(world, rng, args, mut_cycle, mut_i, speed, frame_dir, live=True)
    else:
        _run(world, rng, args, mut_cycle, mut_i, speed, frame_dir, live=False)


def _run(world, rng, args, mut_cycle, mut_i, speed, frame_dir, live):
    target = args.steps if args.steps > 0 else 10**9
    while world.step < target:
        for _ in range(speed):
            step_world(world, rng)
        if live:
            sys.stdout.write("\x1b[H\x1b[J" + render_terminal(world) + "\n")
            sys.stdout.flush()
            key = read_key()
            if key == "q":
                break
            elif key == "f":
                world.plants.cells = np.minimum(world.plants.cells + PLANT_E * 0.6, PLANT_E)
            elif key == "p":
                spawn(
                    world.preds,
                    10,
                    rng,
                    world.preds.genome[: max(world.preds.n, 1)].mean(axis=0)
                    if world.preds.n
                    else None,
                )
            elif key == "P":
                spawn(
                    world.prey,
                    20,
                    rng,
                    world.prey.genome[: max(world.prey.n, 1)].mean(axis=0)
                    if world.prey.n
                    else None,
                )
            elif key == "m":
                mut_i = (mut_i + 1) % len(mut_cycle)
                world.mut = mut_cycle[mut_i]
            elif key == "k":
                if world.prey.n:
                    _compact(world.prey, np.random.default_rng().random(world.prey.n) > 0.5)
                if world.preds.n:
                    _compact(world.preds, np.random.default_rng().random(world.preds.n) > 0.5)
            elif key == "+":
                speed = min(speed + 1, 20)
            elif key == "-":
                speed = max(speed - 1, 1)
        if frame_dir and world.step % args.frame_every == 0:
            render_png(world, os.path.join(frame_dir, f"frame_{world.step:06d}.png"))
        if not live and world.step % 100 == 0 and world.step > 0:
            nprey, npred = world.prey.n, world.preds.n
            print(
                f"step {world.step} prey {nprey} preds {npred} plants {world.plants.cells.sum():.0f}",
                file=sys.stderr,
            )

    # always save a final frame
    if frame_dir:
        render_png(world, os.path.join(frame_dir, f"frame_{world.step:06d}.png"))
        print(f"saved frames to {frame_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
