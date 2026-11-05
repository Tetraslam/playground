"""Breed Redcode warriors against the hill.

A genetic algorithm over raw instruction lists. Genomes start as random noise
(nothing copied from the hand-written warriors), get scored by fighting every
hill warrior through `tournament.play`, and reproduce by mutation and two-point
crossover. With `--coevolve K`, every K generations the champion joins the hill
it is being scored against, so the population has to keep beating its own past.

    uv run python toys/coreloom/evolve.py --generations 60 --seed 1
    uv run python toys/coreloom/evolve.py --coevolve 10 --history scratch/evo.json

Everything flows from `--seed`; worker count never changes the result.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import tournament
import vm

HERE = Path(__file__).parent
CANDIDATE = (
    "candidate"  # one fixed name, so every candidate in a generation faces the same placements
)
MAXLEN = 20

# Weighted toward the ops that real warriors are made of; DAT stays common because
# it is both the bomb and the data cell.
OP_WEIGHTS = {
    "DAT": 4,
    "MOV": 8,
    "ADD": 4,
    "SUB": 2,
    "JMP": 4,
    "JMZ": 2,
    "JMN": 2,
    "DJN": 3,
    "CMP": 2,
    "SPL": 4,
    "SLT": 1,
}
MODE_WEIGHTS = {"#": 3, "$": 4, "@": 3, "<": 2}


@dataclass
class Genome:
    code: list[vm.Insn]
    start: int = 0
    parent: str = "noise"

    def warrior(self, name: str = CANDIDATE) -> vm.Warrior:
        return vm.Warrior(name, list(self.code), self.start % len(self.code), "evolve.py")

    def key(self) -> tuple:
        return (tuple(self.code), self.start % len(self.code))


def _pick(rng: random.Random, weights: dict[str, int]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _field(rng: random.Random, length: int) -> int:
    """Operands: mostly local (pointing into own code), sometimes a bombing stride."""
    r = rng.random()
    if r < 0.6:
        v = rng.randint(-length, length + 2)
    elif r < 0.9:
        v = rng.randint(-200, 200)
    else:
        v = rng.randrange(vm.CORESIZE)
    return v % vm.CORESIZE


def random_insn(rng: random.Random, length: int) -> vm.Insn:
    return vm.Insn(
        _pick(rng, OP_WEIGHTS),
        _pick(rng, MODE_WEIGHTS),
        _field(rng, length),
        _pick(rng, MODE_WEIGHTS),
        _field(rng, length),
    )


def random_genome(rng: random.Random) -> Genome:
    n = rng.randint(2, 8)
    return Genome([random_insn(rng, n) for _ in range(n)], rng.randrange(n))


def _nudge(rng: random.Random, v: int) -> int:
    if rng.random() < 0.7:
        v += rng.choice((-1, 1)) * rng.randint(1, 8)
    else:
        v = _field(rng, 8)
    return v % vm.CORESIZE


def mutate(g: Genome, rng: random.Random) -> Genome:
    code, start = list(g.code), g.start
    for _ in range(1 + (rng.random() < 0.4) + (rng.random() < 0.15)):
        i = rng.randrange(len(code))
        r = rng.random()
        op, am, a, bm, b = code[i]
        if r < 0.15:
            code[i] = code[i]._replace(op=_pick(rng, OP_WEIGHTS))
        elif r < 0.30:
            code[i] = code[i]._replace(
                amode=am if rng.random() < 0.5 else _pick(rng, MODE_WEIGHTS),
                bmode=_pick(rng, MODE_WEIGHTS),
            )
        elif r < 0.55:
            code[i] = code[i]._replace(a=_nudge(rng, a))
        elif r < 0.80:
            code[i] = code[i]._replace(b=_nudge(rng, b))
        elif r < 0.88 and len(code) < MAXLEN:
            code.insert(i, random_insn(rng, len(code)) if rng.random() < 0.6 else code[i])
        elif r < 0.95 and len(code) > 1:
            del code[i]
        else:
            start = rng.randrange(len(code))
    return Genome(code, start % len(code), g.parent)


def crossover(x: Genome, y: Genome, rng: random.Random) -> Genome:
    """Two-point: x's head and tail around a slice of y."""
    i, j = sorted(rng.randrange(len(x.code) + 1) for _ in range(2))
    k, m = sorted(rng.randrange(len(y.code) + 1) for _ in range(2))
    code = (x.code[:i] + y.code[k:m] + x.code[j:])[:MAXLEN] or list(x.code[:1])
    return Genome(code, x.start % len(code), x.parent)


# ----------------------------------------------------------------- scoring


def _score(job) -> tuple[float, list[int]]:
    """Points per round (0..3) overall, plus total points vs each hill warrior."""
    genome, hill, rounds, seed, max_cycles = job
    field_ = [genome.warrior(), *hill]
    board = tournament.play(
        field_,
        rounds,
        seed,
        max_cycles=max_cycles,
        pairings=[(0, k) for k in range(1, len(field_))],
    )
    per = [board.pairs[(CANDIDATE, h.name)].points for h in hill]
    return board.score(CANDIDATE), per


def evaluate(pop, hill, rounds, seed, max_cycles, pool):
    jobs = [(g, hill, rounds, seed, max_cycles) for g in pop]
    return list(pool.map(_score, jobs)) if pool else [_score(j) for j in jobs]


# ---------------------------------------------------------------- the loop


def _tourney(rng, pop, fit, k=3):
    return pop[max(rng.sample(range(len(pop)), k), key=lambda i: fit[i])]


def evolve(hill, *, generations, pop_size, rounds, seed, max_cycles, coevolve, elite, pool, log):
    rng = random.Random(seed)
    pop = [random_genome(rng) for _ in range(pop_size)]
    hill = list(hill)
    history, champs = [], []
    best: tuple[float, Genome, list[int]] | None = None

    for gen in range(generations):
        gseed = rng.getrandbits(
            32
        )  # fresh placements each generation, shared by the whole population
        scored = evaluate(pop, hill, rounds, gseed, max_cycles, pool)
        fit = [s for s, _ in scored]
        order = sorted(range(len(pop)), key=lambda i: -fit[i])
        top = order[0]
        ops = Counter(insn.op for g in pop for insn in g.code)
        total = sum(ops.values())
        history.append(
            {
                "gen": gen,
                "best": round(fit[top], 4),
                "mean": round(sum(fit) / len(fit), 4),
                "hill": [h.name for h in hill],
                "best_len": len(pop[top].code),
                "ops": {op: round(ops[op] / total, 4) for op in vm.OPS},
                "champion": pop[top].warrior(f"gen{gen}").redcode(),
            }
        )
        log(
            f"gen {gen:3d}  best {fit[top]:.2f}  mean {sum(fit) / len(fit):.2f}  "
            f"len {len(pop[top].code):2d}  hill {len(hill)}  "
            + " ".join(f"{op}:{ops[op] * 100 // total}" for op, _ in ops.most_common(4))
        )

        if best is None or fit[top] >= best[0] or coevolve:
            best = (fit[top], pop[top], scored[top][1])
        if coevolve and gen and gen % coevolve == 0:
            champ = pop[top].warrior(f"gen{gen}")
            hill.append(champ)
            champs.append(champ)
            log(f"         gen{gen} joins the hill")

        nxt = [pop[i] for i in order[:elite]]
        seen = {g.key() for g in nxt}
        while len(nxt) < pop_size:
            r = rng.random()
            if r < 0.3:
                child = crossover(_tourney(rng, pop, fit), _tourney(rng, pop, fit), rng)
                child = mutate(child, rng) if rng.random() < 0.5 else child
            elif r < 0.95:
                child = mutate(_tourney(rng, pop, fit), rng)
            else:
                child = random_genome(rng)  # immigrants keep diversity alive
            if child.key() not in seen:
                seen.add(child.key())
                nxt.append(child)
        pop = nxt

    return best, hill, champs, history


def render(name, genome, fitness, per, hill, args) -> str:
    w = genome.warrior(name)
    record = ", ".join(f"{h.name} {p}/{3 * args.rounds}" for h, p in zip(hill, per, strict=True))
    header = [
        f";name {name}",
        ";author evolve.py",
        f"; bred from noise: seed {args.seed}, {args.generations} generations, "
        f"pop {args.pop}, coevolve {args.coevolve or 'off'}",
        f"; final generation: {fitness:.2f} pts/round vs the hill",
        f"; points per opponent: {record}",
        f"ORG {w.start}",
    ]
    return "\n".join(header + [str(i) for i in w.code]) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--generations", type=int, default=60)
    p.add_argument("--pop", type=int, default=48)
    p.add_argument("--rounds", type=int, default=4, help="rounds per hill opponent per candidate")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument(
        "--max-cycles",
        type=int,
        default=8000,
        help="cap per round while breeding (ties are slow; the tournament uses 80000)",
    )
    p.add_argument("--elite", type=int, default=4)
    p.add_argument(
        "--coevolve",
        type=int,
        default=0,
        metavar="K",
        help="every K generations the champion joins the hill",
    )
    p.add_argument(
        "--hill", nargs="*", help="warrior stems to breed against (default: all hand-written)"
    )
    p.add_argument(
        "--jobs", "-j", type=int, default=None, help="worker processes (default: all cores)"
    )
    p.add_argument(
        "--out", type=Path, help="write the champion here (default: warriors/evolved_s<seed>.red)"
    )
    p.add_argument(
        "--history", type=Path, help="per-generation JSON (fitness, op mix, champions) for viz"
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    hill = [
        w
        for w in tournament.load_warriors(only=args.hill)
        if args.hill or not w.name.startswith("evolved")
    ]
    if not hill:
        raise SystemExit("empty hill")
    log = (lambda *_: None) if args.quiet else (lambda m: print(m, file=sys.stderr, flush=True))
    log(f"breeding against {len(hill)}: {' '.join(h.name for h in hill)}")

    t0 = time.time()
    jobs = args.jobs or os.cpu_count() or 1
    pool = ProcessPoolExecutor(max_workers=jobs) if jobs > 1 else None
    try:
        (fitness, genome, per), final_hill, champs, history = evolve(
            hill,
            generations=args.generations,
            pop_size=args.pop,
            rounds=args.rounds,
            seed=args.seed,
            max_cycles=args.max_cycles,
            coevolve=args.coevolve,
            elite=args.elite,
            pool=pool,
            log=log,
        )
    finally:
        if pool:
            pool.shutdown()

    name = f"evolved_s{args.seed}"
    out = args.out or HERE / "warriors" / f"{name}.red"
    out.write_text(render(out.stem, genome, fitness, per, final_hill, args))
    log(f"champion -> {out}  ({time.time() - t0:.0f}s)")
    if args.history:
        args.history.parent.mkdir(parents=True, exist_ok=True)
        args.history.write_text(
            json.dumps(
                {
                    "seed": args.seed,
                    "args": {
                        k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()
                    },
                    "generations": history,
                },
                indent=1,
            )
        )
    print(out.read_text(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
