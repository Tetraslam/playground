"""coreloom viz: watch a battle live in the terminal, or render it to PNG.

    uv run python toys/coreloom/viz.py watch dwarf scout --seed 3
    uv run python toys/coreloom/viz.py spacetime dwarf scout -o out.png
    uv run python toys/coreloom/viz.py film dwarf scout -o frames/ --every 200

Warriors are file stems in warriors/ or paths to .red files. Each cell of the
core is colored by its last writer: bright for live code, dim for DAT (bombs
and dead data), white-hot where something was just written, and a pale dot
where a process is about to execute. Stdlib only, like the rest of coreloom.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import tournament  # noqa: E402
import vm  # noqa: E402

PALETTE = [
    (255, 99, 72),  # ember
    (72, 196, 255),  # sky
    (140, 230, 90),  # moss
    (255, 196, 60),  # amber
    (200, 120, 255),  # violet
    (255, 110, 190),  # rose
    (80, 230, 200),  # teal
    (230, 230, 120),  # straw
]
EMPTY = (16, 16, 22)
NEUTRAL = (70, 70, 80)  # written by nobody but not blank (shouldn't happen)
RGB = tuple[int, int, int]


def _mix(c: RGB, d: RGB, t: float) -> RGB:
    return (
        int(c[0] + (d[0] - c[0]) * t),
        int(c[1] + (d[1] - c[1]) * t),
        int(c[2] + (d[2] - c[2]) * t),
    )


def _scale(c: RGB, k: float) -> RGB:
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


def load(specs: list[str]) -> list[vm.Warrior]:
    out = []
    for spec in specs:
        path = Path(spec)
        if not path.suffix:
            path = tournament.WARRIOR_DIR / f"{spec}.red"
        if not path.exists():
            have = ", ".join(sorted(p.stem for p in tournament.WARRIOR_DIR.glob("*.red")))
            raise SystemExit(f"no warrior {spec!r} (have: {have})")
        w = tournament.load_warrior(path)
        w.name = path.stem
        out.append(w)
    return out


class WriteLog(list):
    """Drop-in for Battle.owner that also stamps the cycle of every write.

    The VM records the writer of each cell via ``owner[addr] = w``, so swapping
    the list catches every write (MOV, ADD/SUB, DJN, predecrement), including
    the ones that rewrite a cell with identical contents, like an imp.
    """

    def __init__(self, battle: vm.Battle) -> None:
        super().__init__(battle.owner)
        self.battle = battle
        self.stamp = [-(10**9)] * len(self)

    def __setitem__(self, i, v) -> None:
        super().__setitem__(i, v)
        self.stamp[i] = self.battle.cycle


class Painter:
    """Turns a Battle into per-cell colors, glowing where writes just landed."""

    def __init__(self, battle: vm.Battle, glow: int = 64) -> None:
        self.b = battle
        self.glow = glow  # cycles for a write's glow to fade
        self.log = WriteLog(battle)
        battle.owner = self.log

    def colors(self, dim: float = 1.0) -> list[RGB]:
        """dim < 1 darkens cells that were not written within the glow window."""
        b, stamp, now, glow = self.b, self.log.stamp, self.b.cycle, self.glow
        out = []
        for i in range(b.coresize):
            w = b.owner[i]
            if w < 0:
                c = EMPTY if (b.op[i] == vm.DAT and b.a[i] == 0 and b.b[i] == 0) else NEUTRAL
            else:
                base = PALETTE[w % len(PALETTE)]
                c = _scale(base, 0.38) if b.op[i] == vm.DAT else base
            h = 1 - (now - stamp[i]) / glow
            if h > 0:
                c = _mix(c, (255, 255, 255), 0.75 * h)
            elif dim < 1:
                c = _scale(c, dim)
            out.append(c)
        for w, q in enumerate(b.queues):
            if b.alive[w]:
                tint = _mix(PALETTE[w % len(PALETTE)], (255, 255, 255), 0.8)
                for pc in q:
                    out[pc] = tint
        return out

    def territory(self) -> list[int]:
        """Cells each warrior wrote last (code and bombs alike)."""
        counts = [0] * len(self.b.warriors)
        for w in self.b.owner:
            if w >= 0:
                counts[w] += 1
        return counts


# ------------------------------------------------------------------- terminal


def _fg(c: RGB) -> str:
    return f"\x1b[38;2;{c[0]};{c[1]};{c[2]}m"


def _bg(c: RGB) -> str:
    return f"\x1b[48;2;{c[0]};{c[1]};{c[2]}m"


def draw_grid(colors: list[RGB], width: int) -> list[str]:
    """Half-block rendering: each terminal row shows two core rows."""
    rows = [colors[i : i + width] for i in range(0, len(colors), width)]
    if len(rows) % 2:
        rows.append([EMPTY] * width)
    lines = []
    for top, bot in zip(rows[::2], rows[1::2]):
        bot = bot + [EMPTY] * (len(top) - len(bot))
        parts, last = [], None
        for t, u in zip(top, bot):
            key = (t, u)
            if key != last:
                parts.append(_fg(t) + _bg(u))
                last = key
            parts.append("▀")
        lines.append("".join(parts) + "\x1b[0m")
    return lines


def sidebar(
    battle: vm.Battle, painter: Painter, speed: int, paused: bool, seed: int, width: int
) -> list[str]:
    terr = painter.territory()
    total = max(1, sum(terr))
    lines = []
    for w, warrior in enumerate(battle.warriors):
        c = PALETTE[w % len(PALETTE)]
        state = f"{len(battle.queues[w]):>2} proc" if battle.alive[w] else " dead  "
        lines.append(f"{_fg(c)}█\x1b[0m {warrior.name:<14.14} {state}  {terr[w]:>4} cells")
    bar = []
    for w, t in enumerate(terr):
        bar.append(_bg(PALETTE[w % len(PALETTE)]) + " " * round(width * t / total))
    lines.append("".join(bar)[:10_000] + "\x1b[0m")
    status = "paused" if paused else f"x{speed} cycles/frame"
    lines.append(
        f"cycle {battle.cycle:>6}/{battle.maxcycles}  seed {seed}  {status}"
        "   [space] pause  [.] step  [+/-] speed  [r]estart  [n]ext seed  [q]uit"
    )
    return lines


def verdict(battle: vm.Battle) -> str:
    live = [i for i, a in enumerate(battle.alive) if a]
    if len(live) == 1 and len(battle.warriors) > 1:
        c = PALETTE[live[0] % len(PALETTE)]
        return f"{_fg(c)}{battle.warriors[live[0]].name} wins\x1b[0m at cycle {battle.cycle}"
    return f"tie at cycle {battle.cycle}"


class Keys:
    """cbreak stdin, restored on exit."""

    def __enter__(self) -> Keys:
        import termios
        import tty

        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
        return self

    def __exit__(self, *exc) -> None:
        import termios

        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()

    def poll(self, timeout: float) -> str:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return os.read(self.fd, 32).decode(errors="ignore") if r else ""


def watch(
    warriors: list[vm.Warrior], seed: int, speed: int, fps: float, width: int | None, loop: bool
) -> None:
    if not sys.stdin.isatty():
        raise SystemExit("watch needs a terminal; try `spacetime` or `film` for files")
    cols = shutil.get_terminal_size((100, 40)).columns
    width = width or max(40, min(cols - 2, 125))

    def fresh(s: int) -> tuple[vm.Battle, Painter]:
        b = vm.Battle(warriors, seed=s)
        return b, Painter(b, glow=max(32, speed * 6))

    battle, painter = fresh(seed)
    paused, step_once, ended_at = False, False, None
    with Keys() as keys:
        while True:
            t0 = time.perf_counter()
            if not battle.done and (not paused or step_once):
                for _ in range(1 if step_once else speed):
                    if battle.done:
                        break
                    battle.step()
                step_once = False
            frame = ["\x1b[H"]
            frame += draw_grid(painter.colors(), width)
            frame += sidebar(battle, painter, speed, paused, seed, width)
            frame.append((verdict(battle) if battle.done else "").ljust(60))
            sys.stdout.write("\x1b[K\n".join(frame) + "\x1b[K")
            sys.stdout.flush()

            if battle.done and loop:
                ended_at = ended_at or time.perf_counter()
                if time.perf_counter() - ended_at > 2.5:
                    seed += 1
                    battle, painter = fresh(seed)
                    ended_at = None
            key = keys.poll(max(0.0, 1 / fps - (time.perf_counter() - t0)))
            for ch in key:
                if ch in "qQ\x1b":
                    return
                if ch == " ":
                    paused = not paused
                elif ch == ".":
                    paused, step_once = True, True
                elif ch in "+=":
                    speed = min(speed * 2, 8192)
                    painter.glow = max(32, speed * 6)
                elif ch in "-_":
                    speed = max(speed // 2, 1)
                    painter.glow = max(32, speed * 6)
                elif ch in "rR":
                    battle, painter = fresh(seed)
                elif ch in "nN":
                    seed += 1
                    battle, painter = fresh(seed)
                    ended_at = None


# ------------------------------------------------------------------------ png


def write_png(path: Path, pixels: list[list[RGB]]) -> None:
    h, w = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in pixels)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def core_image(painter: Painter, width: int, px: int, bar: int = 6) -> list[list[RGB]]:
    """The core as a width-wide grid of px-sized cells, plus a territory bar."""
    colors = painter.colors()
    gap = (8, 8, 12)
    rows = []
    for r in range(0, len(colors), width):
        line: list[RGB] = []
        for c in colors[r : r + width]:
            line += [c] * (px - 1) + [gap]
        line += [EMPTY] * (width * px - len(line))
        rows += [line] * (px - 1) + [[gap] * len(line)]
    terr = painter.territory()
    total = max(1, sum(terr))
    strip: list[RGB] = []
    for w, t in enumerate(terr):
        strip += [PALETTE[w % len(PALETTE)]] * round(len(rows[0]) * t / total)
    strip = (strip + [EMPTY] * len(rows[0]))[: len(rows[0])]
    return rows + [[EMPTY] * len(rows[0])] * 2 + [strip] * bar


def spacetime(
    warriors: list[vm.Warrior], seed: int, every: int, fold: int
) -> tuple[list[list[RGB]], vm.Battle]:
    """One row per `every` cycles, x = core address, one pixel per `fold` cells.

    Cells written during the row's interval glow; the rest are dimmed, so the
    picture shows where each warrior is *acting*, not just what it owns.
    """
    battle = vm.Battle(warriors, seed=seed)
    painter = Painter(battle, glow=every)
    rows = []
    while True:
        colors = painter.colors(dim=0.5)
        row = []
        for i in range(0, len(colors), fold):
            row.append(
                max(colors[i : i + fold], key=sum)
            )  # brightest wins: keep thin trails visible
        rows.append(row)
        if battle.done:
            break
        for _ in range(every):
            if battle.done:
                break
            battle.step()
    return rows, battle


def film(
    warriors: list[vm.Warrior], seed: int, every: int, outdir: Path, width: int, px: int, tail: int
) -> int:
    battle = vm.Battle(warriors, seed=seed)
    painter = Painter(battle, glow=every * 3)
    outdir.mkdir(parents=True, exist_ok=True)
    n = 0
    while True:
        write_png(outdir / f"{n:05d}.png", core_image(painter, width, px))
        n += 1
        if battle.done:
            for _ in range(tail):  # hold the final frame so the loop doesn't snap back
                write_png(outdir / f"{n:05d}.png", core_image(painter, width, px))
                n += 1
            return n
        for _ in range(every):
            if battle.done:
                break
            battle.step()


OP_COLORS = {
    "DAT": (90, 90, 105),
    "MOV": (255, 99, 72),
    "ADD": (255, 196, 60),
    "SUB": (230, 140, 50),
    "JMP": (72, 196, 255),
    "JMZ": (60, 130, 220),
    "JMN": (110, 110, 240),
    "DJN": (140, 230, 90),
    "CMP": (255, 110, 190),
    "SPL": (200, 120, 255),
    "SLT": (80, 230, 200),
}


def evolution(history: dict, colw: int, height: int = 240, fit_h: int = 140) -> list[list[RGB]]:
    """evolve.py --history as a picture: opcode strata on top, fitness below.

    Top: one column per generation, stacked by the population's opcode mix.
    Bottom: best (white) and mean (gray) fitness on a 0..3 pts/round scale.
    Amber ticks mark generations where a champion joined the hill.
    """
    gens = history["generations"]
    w = len(gens) * colw
    bg, grid = (12, 12, 18), (34, 34, 44)
    img = [[bg] * w for _ in range(height + 6 + fit_h)]
    for x0, g in enumerate(gens):
        y = 0.0
        for op in vm.OPS:
            share = g["ops"].get(op, 0.0)
            y1 = y + share * height
            for row in img[round(y) : round(y1)]:
                row[x0 * colw : (x0 + 1) * colw] = [OP_COLORS[op]] * colw
            y = y1
    top = height + 6
    for pts in (1, 2, 3):  # gridlines at 1, 2, 3 pts/round
        img[top + fit_h - 1 - round(pts / 3 * (fit_h - 1))] = [grid] * w
    for i, g in enumerate(gens):
        if i and len(g["hill"]) > len(gens[i - 1]["hill"]):
            for row in img[top : top + fit_h]:
                row[i * colw : i * colw + 2] = [(255, 196, 60)] * 2

    def line(key: str, color: RGB) -> None:
        prev = None
        for i, g in enumerate(gens):
            y = top + fit_h - 1 - round(min(g[key], 3) / 3 * (fit_h - 1))
            for x in range(i * colw, (i + 1) * colw):
                lo, hi = (y, y) if prev is None else (min(prev, y), max(prev, y))
                for yy in range(lo, hi + 1):
                    img[yy][x] = color
                prev = y

    line("mean", (130, 130, 145))
    line("best", (255, 255, 255))
    return img


def describe(battle: vm.Battle) -> str:
    live = [i for i, a in enumerate(battle.alive) if a]
    if len(live) == 1 and len(battle.warriors) > 1:
        return f"{battle.warriors[live[0]].name} wins at cycle {battle.cycle}"
    return f"tie at cycle {battle.cycle}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="coreloom-viz", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "warriors", nargs="+", help="warrior stems (warriors/<stem>.red) or .red paths"
        )
        sp.add_argument("--seed", type=int, default=1)

    w = sub.add_parser("watch", help="live TUI")
    common(w)
    w.add_argument("--speed", type=int, default=16, help="cycles per frame (+/- live)")
    w.add_argument("--fps", type=float, default=30)
    w.add_argument("--width", type=int, help="cells per row (default: fit terminal)")
    w.add_argument(
        "--loop", action="store_true", help="auto-advance to the next seed after each round"
    )

    s = sub.add_parser("spacetime", help="PNG: time flows down, core address across")
    common(s)
    s.add_argument("-o", "--out", type=Path, required=True)
    s.add_argument(
        "--every", type=int, help="cycles per row (default: fit the round into ~--rows rows)"
    )
    s.add_argument("--rows", type=int, default=500)
    s.add_argument("--fold", type=int, default=4, help="cells per pixel (brightest shown)")

    f = sub.add_parser("snap", help="PNG of the core at one cycle")
    common(f)
    f.add_argument("-o", "--out", type=Path, required=True)
    f.add_argument("--cycle", type=int, default=2000)
    f.add_argument("--width", type=int, default=100)
    f.add_argument("--px", type=int, default=6)

    m = sub.add_parser("film", help="PNG frame sequence (feed to tools/blender.sh encode)")
    common(m)
    m.add_argument("-o", "--out", type=Path, required=True)
    m.add_argument("--every", type=int, default=200)
    m.add_argument("--width", type=int, default=100)
    m.add_argument("--px", type=int, default=5)
    m.add_argument("--tail", type=int, default=24, help="extra copies of the final frame")

    e = sub.add_parser("evolution", help="PNG of an evolve.py --history file")
    e.add_argument("history", type=Path)
    e.add_argument("-o", "--out", type=Path, required=True)
    e.add_argument("--colw", type=int, help="pixels per generation (default: ~800 px wide)")

    args = p.parse_args(argv)
    if args.cmd == "evolution":
        hist = json.loads(args.history.read_text())
        colw = args.colw or max(1, 800 // len(hist["generations"]))
        write_png(args.out, evolution(hist, colw))
        print(f"{args.out}: {len(hist['generations'])} generations")
        return 0
    warriors = load(args.warriors)
    if args.cmd == "watch":
        watch(warriors, args.seed, args.speed, args.fps, args.width, args.loop)
    elif args.cmd == "spacetime":
        every = args.every or max(1, -(-vm.battle(warriors, args.seed).cycles // args.rows))
        rows, battle = spacetime(warriors, args.seed, every, args.fold)
        write_png(args.out, rows)
        print(f"{args.out}: {len(rows[0])}x{len(rows)}, {describe(battle)}")
    elif args.cmd == "snap":
        battle = vm.Battle(warriors, seed=args.seed)
        painter = Painter(battle, glow=1)
        while battle.cycle < args.cycle and not battle.done:
            battle.step()
        write_png(args.out, core_image(painter, args.width, args.px))
        print(f"{args.out}: cycle {battle.cycle}, {describe(battle)}")
    elif args.cmd == "film":
        n = film(warriors, args.seed, args.every, args.out, args.width, args.px, args.tail)
        print(f"{args.out}: {n} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
