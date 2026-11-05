"""Round-robin tournament over coreloom warriors.

Every pair of warriors fights `rounds` rounds. Each round gets its own seed
derived from (seed, pair, round index), so results are identical whether the
rounds run serially or across processes, and adding a warrior never reshuffles
the seeds of pairings that already existed.

Scoring per round: win 3, tie 1, loss 0.
"""

from __future__ import annotations

import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import vm

WIN, TIE, LOSS = 3, 1, 0
WARRIOR_DIR = Path(__file__).parent / "warriors"


def load_warrior(path: Path):
    warrior = vm.parse_redcode(path.read_text())
    if not getattr(warrior, "name", None):
        warrior.name = path.stem
    return warrior


def load_warriors(directory: Path = WARRIOR_DIR, only: list[str] | None = None) -> list:
    paths = sorted(directory.glob("*.red"))
    if only:
        wanted = set(only)
        paths = [p for p in paths if p.stem in wanted]
        missing = wanted - {p.stem for p in paths}
        if missing:
            raise SystemExit(f"no such warrior(s): {', '.join(sorted(missing))}")
    warriors = [load_warrior(p) for p in paths]
    # File stem is the identity: keep names unique even if two files share a ;name.
    for warrior, path in zip(warriors, paths):
        warrior.name = path.stem
    return warriors


def round_seed(seed: int, a: str, b: str, r: int) -> int:
    return random.Random(f"{seed}:{a}:{b}:{r}").getrandbits(32)


@dataclass
class Record:
    wins: int = 0
    ties: int = 0
    losses: int = 0

    @property
    def points(self) -> int:
        return WIN * self.wins + TIE * self.ties + LOSS * self.losses

    @property
    def played(self) -> int:
        return self.wins + self.ties + self.losses


@dataclass
class Scoreboard:
    names: list[str]
    rounds: int
    seed: int
    totals: dict[str, Record] = field(default_factory=dict)
    # pairs[(a, b)] is a's record against b.
    pairs: dict[tuple[str, str], Record] = field(default_factory=dict)

    def __post_init__(self):
        for n in self.names:
            self.totals.setdefault(n, Record())

    def record(self, a: str, b: str, winner: int | None) -> None:
        ra = self.pairs.setdefault((a, b), Record())
        rb = self.pairs.setdefault((b, a), Record())
        if winner is None:
            for rec in (ra, rb, self.totals[a], self.totals[b]):
                rec.ties += 1
        elif winner == 0:
            ra.wins += 1
            rb.losses += 1
            self.totals[a].wins += 1
            self.totals[b].losses += 1
        else:
            rb.wins += 1
            ra.losses += 1
            self.totals[b].wins += 1
            self.totals[a].losses += 1

    def ranking(self) -> list[tuple[str, Record]]:
        return sorted(self.totals.items(), key=lambda kv: (-kv[1].points, -kv[1].wins, kv[0]))

    def score(self, name: str) -> float:
        """Average points per round played, 0..3."""
        rec = self.totals[name]
        return rec.points / rec.played if rec.played else 0.0

    def render(self) -> str:
        ranked = self.ranking()
        width = max([len(n) for n in self.names] + [7])
        lines = [
            f"coreloom  {len(self.names)} warriors  {self.rounds} rounds/pair  seed {self.seed}",
            "",
            f"{'#':>2}  {'warrior':<{width}}  {'pts':>5}  {'W':>4} {'T':>4} {'L':>4}  {'pts/rd':>6}",
        ]
        for i, (name, rec) in enumerate(ranked, 1):
            lines.append(
                f"{i:>2}  {name:<{width}}  {rec.points:>5}  "
                f"{rec.wins:>4} {rec.ties:>4} {rec.losses:>4}  {self.score(name):>6.2f}"
            )
        if len(self.names) <= 12:
            order = [n for n, _ in ranked]
            short = [n[:5] for n in order]
            lines += ["", "head to head (row's W-T-L vs column)", ""]
            lines.append(" " * (width + 2) + "  ".join(f"{s:>8}" for s in short))
            for a in order:
                cells = []
                for b in order:
                    rec = self.pairs.get((a, b))
                    cells.append(
                        f"{'-':>8}"
                        if a == b or rec is None
                        else f"{rec.wins}-{rec.ties}-{rec.losses}".rjust(8)
                    )
                lines.append(f"{a:<{width}}  " + "  ".join(cells))
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "seed": self.seed,
            "rounds": self.rounds,
            "ranking": [
                {
                    "name": n,
                    "points": r.points,
                    "wins": r.wins,
                    "ties": r.ties,
                    "losses": r.losses,
                    "score": round(self.score(n), 4),
                }
                for n, r in self.ranking()
            ],
            "pairs": [
                {"a": a, "b": b, "wins": r.wins, "ties": r.ties, "losses": r.losses}
                for (a, b), r in sorted(self.pairs.items())
            ],
        }


def _fight(job):
    """Returns the winner as 0 (pair's a), 1 (pair's b) or None.

    Odd rounds swap the order passed to the VM so neither side always moves first.
    """
    (a, b), rseed, max_cycles, swap = job
    winner = vm.run_round([b, a] if swap else [a, b], seed=rseed, max_cycles=max_cycles)
    return winner if winner is None or not swap else 1 - winner


def _jobs(warriors, rounds, seed, max_cycles, pairings):
    for i, j in pairings:
        a, b = warriors[i], warriors[j]
        for r in range(rounds):
            yield (i, j), ((a, b), round_seed(seed, a.name, b.name, r), max_cycles, r % 2 == 1)


def play(
    warriors: list,
    rounds: int,
    seed: int,
    *,
    max_cycles: int = 80_000,
    jobs: int = 1,
    pairings=None,
    progress=None,
) -> Scoreboard:
    """Fight every pairing for `rounds` rounds. Deterministic in `seed` regardless of `jobs`.

    `pairings` defaults to all i<j index pairs; pass a subset to e.g. fight only one
    challenger against the hill. `progress(done, total)` is called after each round.
    """
    names = [w.name for w in warriors]
    if len(set(names)) != len(names):
        raise ValueError(f"warrior names must be unique: {names}")
    pairings = list(pairings if pairings is not None else combinations(range(len(warriors)), 2))
    board = Scoreboard(names, rounds, seed)
    work = list(_jobs(warriors, rounds, seed, max_cycles, pairings))
    total = len(work)

    if jobs > 1 and total > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            results = pool.map(_fight, [w for _, w in work], chunksize=max(1, total // (jobs * 8)))
            for done, (((i, j), _), winner) in enumerate(zip(work, results), 1):
                board.record(names[i], names[j], winner)
                if progress:
                    progress(done, total)
    else:
        for done, ((i, j), job) in enumerate(work, 1):
            board.record(names[i], names[j], _fight(job))
            if progress:
                progress(done, total)
    return board


def score_vs(
    candidate, hill: list, rounds: int, seed: int, *, max_cycles: int = 80_000, jobs: int = 1
) -> float:
    """Average points per round (0..3) for `candidate` fighting each hill warrior.

    The hill fights only the candidate, not itself, so this is cheap enough for an evolver.
    """
    field_ = [candidate, *hill]
    board = play(
        field_,
        rounds,
        seed,
        max_cycles=max_cycles,
        jobs=jobs,
        pairings=[(0, k) for k in range(1, len(field_))],
    )
    return board.score(candidate.name)
