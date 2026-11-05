"""Coreloom VM: an ICWS'88-flavored Redcode machine.

The core is five parallel int arrays (op, A mode, A field, B mode, B field) so
the evolver can afford thousands of rounds. ``Insn`` is the public, immutable
view of one cell.
"""

from __future__ import annotations

import random
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

CORESIZE = 4000
MAXPROC = 64
MAXCYCLES = 80_000
MAXLENGTH = 100
MINDISTANCE = 100

OPS = ("DAT", "MOV", "ADD", "SUB", "JMP", "JMZ", "JMN", "DJN", "CMP", "SPL", "SLT")
MODES = ("#", "$", "@", "<")
DAT, MOV, ADD, SUB, JMP, JMZ, JMN, DJN, CMP, SPL, SLT = range(len(OPS))
IMM, DIR, IND, DEC = range(len(MODES))
_OP = {name: i for i, name in enumerate(OPS)}
_MODE = {m: i for i, m in enumerate(MODES)}


class Insn(NamedTuple):
    op: str
    amode: str
    a: int
    bmode: str
    b: int

    def __str__(self) -> str:
        return f"{self.op} {self.amode}{self.a}, {self.bmode}{self.b}"


@dataclass
class Warrior:
    name: str
    code: list[Insn]
    start: int = 0
    author: str = "anonymous"
    source: str = ""

    def redcode(self) -> str:
        """Serialize back to parseable Redcode (used by the evolver)."""
        lines = [f";name {self.name}", f";author {self.author}", f"ORG {self.start}"]
        lines += [str(insn) for insn in self.code]
        return "\n".join(lines) + "\n"


class RedcodeError(ValueError):
    pass


# --------------------------------------------------------------------- parser

_LABEL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_EXPR_RE = re.compile(r"^[A-Za-z0-9_+\-*/%() ]+$")


def _eval(expr: str, labels: dict[str, int], here: int, lineno: int) -> int:
    expr = expr.strip()
    if not expr or not _EXPR_RE.match(expr):
        raise RedcodeError(f"line {lineno}: bad expression {expr!r}")

    def sub(m: re.Match) -> str:
        name = m.group(0)
        if name not in labels:
            raise RedcodeError(f"line {lineno}: unknown label {name!r}")
        return str(labels[name] - here)

    py = _LABEL_RE.sub(sub, expr).replace("/", "//")
    try:
        return int(eval(py, {"__builtins__": {}}, {}))  # digits and + - * // % ( ) only
    except Exception as exc:
        raise RedcodeError(f"line {lineno}: cannot evaluate {expr!r}") from exc


def _operand(text: str, labels: dict[str, int], here: int, lineno: int) -> tuple[str, int]:
    text = text.strip()
    mode = "$"
    if text and text[0] in "#$@<":
        mode, text = text[0], text[1:]
    elif text and text[0] in "{}>*":
        raise RedcodeError(f"line {lineno}: mode {text[0]!r} is ICWS'94, coreloom speaks '88")
    return mode, _eval(text, labels, here, lineno)


def parse_redcode(text: str, name: str | None = None) -> Warrior:
    """Parse a minimal '88 Redcode subset: labels, ORG/END, EQU-free expressions."""
    meta = {"name": name or "unnamed", "author": "anonymous"}
    rows: list[tuple[int, str, str]] = []  # (lineno, opcode, operand text)
    labels: dict[str, int] = {}
    org: tuple[int, str] | None = None

    for lineno, raw in enumerate(text.splitlines(), 1):
        line, _, comment = raw.partition(";")
        tag = comment.strip().split(None, 1)
        if len(tag) == 2 and tag[0] in ("name", "author") and not line.strip():
            if tag[0] == "author" or name is None:
                meta[tag[0]] = tag[1].strip()
        tokens = line.replace(":", " ", 1).split(None, 1) if ":" in line else line.split(None, 1)
        if not tokens:
            continue
        # Peel leading labels until we hit an opcode or pseudo-op.
        while (
            tokens
            and tokens[0].upper().split(".")[0] not in _OP
            and tokens[0].upper() not in ("ORG", "END")
        ):
            label = tokens[0].rstrip(":")
            if not _LABEL_RE.fullmatch(label):
                raise RedcodeError(f"line {lineno}: unknown opcode {tokens[0]!r}")
            labels[label] = len(rows)
            tokens = tokens[1].split(None, 1) if len(tokens) > 1 else []
        if not tokens:
            continue
        opword = tokens[0].upper()
        rest = tokens[1] if len(tokens) > 1 else ""
        if opword in ("ORG", "END"):
            if rest.strip():
                org = (lineno, rest.strip())
            if opword == "END":
                break
            continue
        if "." in opword:
            raise RedcodeError(f"line {lineno}: modifiers like {opword!r} are ICWS'94")
        rows.append((lineno, opword, rest))

    if not rows:
        raise RedcodeError("warrior has no instructions")
    if len(rows) > MAXLENGTH:
        raise RedcodeError(f"warrior is {len(rows)} lines, max {MAXLENGTH}")

    code = []
    for here, (lineno, op, rest) in enumerate(rows):
        parts = [p for p in rest.split(",")] if rest.strip() else []
        if len(parts) > 2:
            raise RedcodeError(f"line {lineno}: too many operands")
        if not parts:
            if op != "DAT":
                raise RedcodeError(f"line {lineno}: {op} needs an operand")
            parts = ["#0"]
        if len(parts) == 1:
            parts = ["#0", parts[0]] if op == "DAT" else [parts[0], "$0"]
        am, a = _operand(parts[0], labels, here, lineno)
        bm, b = _operand(parts[1], labels, here, lineno)
        code.append(Insn(op, am, a % CORESIZE, bm, b % CORESIZE))

    start = 0
    if org:
        start = _eval(org[1], labels, 0, org[0]) % len(code)
    return Warrior(meta["name"], code, start, meta["author"], text)


def load_warrior(path: str | Path) -> Warrior:
    path = Path(path)
    return (
        parse_redcode(path.read_text(), None)
        if _has_name(path)
        else parse_redcode(path.read_text(), path.stem)
    )


def _has_name(path: Path) -> bool:
    return any(line.strip().startswith(";name") for line in path.read_text().splitlines())


# ------------------------------------------------------------------------ VM


@dataclass
class Result:
    winner: int | None  # warrior index, or None for a tie
    cycles: int
    alive: list[bool]
    positions: list[int]


@dataclass
class Battle:
    """One round. Read ``owner`` (last writer per cell, -1 = nobody) for viz."""

    warriors: list[Warrior]
    seed: int = 0
    coresize: int = CORESIZE
    maxcycles: int = MAXCYCLES
    maxproc: int = MAXPROC
    mindistance: int = MINDISTANCE
    positions: list[int] | None = None
    cycle: int = 0
    alive: list[bool] = field(init=False)
    queues: list[deque] = field(init=False)
    owner: list[int] = field(init=False)

    def __post_init__(self) -> None:
        n = self.coresize
        self.op = [DAT] * n
        self.am = [DIR] * n
        self.a = [0] * n
        self.bm = [DIR] * n
        self.b = [0] * n
        self.owner = [-1] * n
        if self.positions is None:
            self.positions = _place(self.warriors, self.seed, n, self.mindistance)
        self.alive = [True] * len(self.warriors)
        self.queues = []
        for idx, (w, base) in enumerate(zip(self.warriors, self.positions)):
            for off, insn in enumerate(w.code):
                self.poke((base + off) % n, insn, idx)
            self.queues.append(deque([(base + w.start) % n]))
        self.turn = 0

    # -- cell access

    def peek(self, addr: int) -> Insn:
        addr %= self.coresize
        return Insn(
            OPS[self.op[addr]],
            MODES[self.am[addr]],
            self.a[addr],
            MODES[self.bm[addr]],
            self.b[addr],
        )

    def poke(self, addr: int, insn: Insn, owner: int = -1) -> None:
        addr %= self.coresize
        self.op[addr] = _OP[insn.op]
        self.am[addr] = _MODE[insn.amode]
        self.a[addr] = insn.a % self.coresize
        self.bm[addr] = _MODE[insn.bmode]
        self.b[addr] = insn.b % self.coresize
        self.owner[addr] = owner

    # -- execution

    @property
    def done(self) -> bool:
        live = sum(self.alive)
        multi = len(self.warriors) > 1
        return self.cycle >= self.maxcycles or live == 0 or (multi and live <= 1)

    def step(self) -> None:
        """Advance one cycle: every live warrior executes one instruction."""
        for w in range(len(self.warriors)):
            if self.alive[w]:
                self._exec(w)
        self.cycle += 1

    def run(self) -> Result:
        while not self.done:
            self.step()
        live = [i for i, a in enumerate(self.alive) if a]
        winner = live[0] if len(live) == 1 and len(self.warriors) > 1 else None
        return Result(winner, self.cycle, list(self.alive), list(self.positions))

    def _exec(self, w: int) -> None:
        n = self.coresize
        op_, am_, a_, bm_, b_, own = self.op, self.am, self.a, self.bm, self.b, self.owner
        q = self.queues[w]
        pc = q.popleft()
        op, amode, afield, bmode, bfield = op_[pc], am_[pc], a_[pc], bm_[pc], b_[pc]

        # A operand. Immediate points at the executing instruction itself.
        if amode == IMM:
            ap = pc
        else:
            ap = (pc + afield) % n
            if amode == DEC:
                b_[ap] = (b_[ap] - 1) % n
                own[ap] = w
            if amode != DIR:
                ap = (ap + b_[ap]) % n
        # '88 latches the A instruction before B is evaluated.
        aop, aam, aa, abm, ab = op_[ap], am_[ap], a_[ap], bm_[ap], b_[ap]
        if amode == IMM:
            aa = afield

        if bmode == IMM:
            bp = pc
        else:
            bp = (pc + bfield) % n
            if bmode == DEC:
                b_[bp] = (b_[bp] - 1) % n
                own[bp] = w
            if bmode != DIR:
                bp = (bp + b_[bp]) % n
        bval = bfield if bmode == IMM else b_[bp]

        nxt = (pc + 1) % n
        if op == DAT:
            pass
        elif op == MOV:
            if amode == IMM:
                b_[bp] = aa
            else:
                op_[bp], am_[bp], a_[bp], bm_[bp], b_[bp] = aop, aam, aa, abm, ab
            own[bp] = w
            q.append(nxt)
        elif op == ADD or op == SUB:
            sign = 1 if op == ADD else -1
            if amode == IMM:
                b_[bp] = (b_[bp] + sign * aa) % n
            else:
                a_[bp] = (a_[bp] + sign * aa) % n
                b_[bp] = (b_[bp] + sign * ab) % n
            own[bp] = w
            q.append(nxt)
        elif op == JMP:
            q.append(ap)
        elif op == JMZ:
            q.append(ap if bval == 0 else nxt)
        elif op == JMN:
            q.append(ap if bval != 0 else nxt)
        elif op == DJN:
            b_[bp] = (b_[bp] - 1) % n
            own[bp] = w
            q.append(ap if b_[bp] != 0 else nxt)
        elif op == CMP:
            if amode == IMM:
                same = aa == bval
            else:
                same = (aop, aam, aa, abm, ab) == (op_[bp], am_[bp], a_[bp], bm_[bp], b_[bp])
            q.append((pc + 2) % n if same else nxt)
        elif op == SLT:
            aval = aa if amode == IMM else ab
            q.append((pc + 2) % n if aval < bval else nxt)
        elif op == SPL:
            q.append(nxt)
            if len(q) < self.maxproc:
                q.append(ap)

        if not q:
            self.alive[w] = False


def _place(warriors: list[Warrior], seed: int, n: int, mindist: int) -> list[int]:
    """First warrior at 0, the rest at seeded offsets that keep code mindist apart."""
    rng = random.Random(seed)
    positions = [0]
    for w in warriors[1:]:
        for _ in range(10_000):
            p = rng.randrange(n)
            if all(
                _gap(p, len(w.code), q, len(warriors[i].code), n) >= mindist
                for i, q in enumerate(positions)
            ):
                positions.append(p)
                break
        else:
            raise ValueError("core too small to place warriors")
    return positions


def _gap(p: int, plen: int, q: int, qlen: int, n: int) -> int:
    return min((q - (p + plen)) % n, (p - (q + qlen)) % n)


def battle(warriors: list[Warrior], seed: int = 0, **kw) -> Result:
    return Battle(warriors, seed=seed, **kw).run()


def run_round(warriors: list[Warrior], seed: int = 0, max_cycles: int = MAXCYCLES) -> int | None:
    """Winner index, or None for a tie."""
    return battle(warriors, seed, maxcycles=max_cycles).winner
