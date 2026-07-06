"""saturn CLI: solve DIMACS instances, trace the search, or sweep the 3-SAT phase transition.

Usage:
    uv run python toys/saturn/main.py solve examples/aim-50.cnf [--trace]
    uv run python toys/saturn/main.py sweep --vars 60 --seed 1
    uv run python toys/saturn/main.py gen --vars 30 --ratio 4.3 --seed 7 > out.cnf
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from saturn import Solver


def parse_dimacs(text: str) -> tuple[int, list[list[int]]]:
    nvars = 0
    clauses: list[list[int]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "c%":
            continue
        if line.startswith("p "):
            parts = line.split()
            # p cnf nvars nclauses
            nvars = int(parts[2])
            continue
        if line[0].isdigit() or line[0] == "-":
            toks = line.split()
            if toks and toks[-1] == "0":
                toks = toks[:-1]
            clauses.append([int(t) for t in toks])
    return nvars, clauses


def gen_3sat(nvars: int, ratio: float, seed: int) -> tuple[int, list[list[int]]]:
    rng = random.Random(seed)
    nclauses = int(nvars * ratio)
    clauses = []
    for _ in range(nclauses):
        vs = rng.sample(range(1, nvars + 1), 3)
        clause = [v if rng.random() < 0.5 else -v for v in vs]
        clauses.append(clause)
    return nvars, clauses


def fmt_model(model: dict[int, bool]) -> str:
    return " ".join(f"{'+' if t else '-'}{v}" for v, t in sorted(model.items()))


def cmd_solve(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.file == "-" else open(args.file).read()
    nvars, clauses = parse_dimacs(text)
    solver = Solver(nvars, clauses, verbose=args.trace)
    t0 = time.perf_counter()
    sat = solver.solve()
    dt = time.perf_counter() - t0
    print(f"instance: {args.file}")
    print(f"vars={nvars} clauses={len(clauses)}")
    print(f"result: {'SAT' if sat else 'UNSAT'}")
    print(f"time: {dt * 1000:.1f} ms")
    print(f"stats: {solver.stats}")
    if sat:
        print(f"model: {fmt_model(solver.model())}")
    return 0 if sat else 10  # 10 = UNSAT exit code, SAT-solver convention


def cmd_gen(args: argparse.Namespace) -> int:
    nvars, clauses = gen_3sat(args.vars, args.ratio, args.seed)
    print(f"c generated 3-SAT  vars={nvars} ratio={args.ratio} seed={args.seed}")
    print(f"p cnf {nvars} {len(clauses)}")
    for c in clauses:
        print(" ".join(str(lit) for lit in c) + " 0")
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    """Run random 3-SAT across clause/var ratios and print an ASCII chart.

    The 3-SAT phase transition sits near alpha ~ 4.27 clauses/variable: below,
    instances are almost always SAT; above, almost always UNSAT. The hard
    region is right at the crossover. saturn's job is to find it empirically.
    """
    ratios = [2.0, 3.0, 3.5, 4.0, 4.25, 4.5, 4.75, 5.0, 5.5, 6.0, 7.0]
    samples = args.samples
    n = args.vars
    print(f"3-SAT phase sweep  vars={n} samples={samples} per ratio")
    print(f"{'ratio':>6} {'sat%':>5} {'decisions':>12} {'conflicts':>12} {'time(ms)':>10}  bar")
    print("-" * 72)
    max_dec = 1
    results = []
    for r in ratios:
        sat_count = 0
        tot_dec = 0
        tot_conf = 0
        tot_time = 0.0
        for s in range(samples):
            nvars, clauses = gen_3sat(n, r, seed=args.seed * 1000 + s)
            solver = Solver(nvars, clauses)
            t0 = time.perf_counter()
            res = solver.solve()
            tot_time += time.perf_counter() - t0
            tot_dec += solver.stats.decisions
            tot_conf += solver.stats.conflicts
            if res:
                sat_count += 1
        avg_dec = tot_dec // samples
        avg_conf = tot_conf // samples
        avg_time = (tot_time / samples) * 1000
        sat_pct = 100 * sat_count // samples
        results.append((r, sat_pct, avg_dec, avg_conf, avg_time))
        max_dec = max(max_dec, avg_dec)

    for r, sat_pct, avg_dec, avg_conf, avg_time in results:
        bar_len = int(40 * avg_dec / max_dec) if max_dec else 0
        bar = "#" * bar_len
        print(f"{r:>6.2f} {sat_pct:>4}% {avg_dec:>12} {avg_conf:>12} {avg_time:>10.1f}  {bar}")
    print("-" * 72)
    print("bar = relative avg decisions per instance (hardness proxy)")
    print("the spike near alpha~4.27 is the phase transition.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="saturn", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("solve", help="solve a DIMACS CNF instance")
    ps.add_argument("file", help="path to .cnf, or - for stdin")
    ps.add_argument("--trace", action="store_true", help="print decisions/conflicts live")
    ps.set_defaults(func=cmd_solve)

    pg = sub.add_parser("gen", help="generate a random 3-SAT instance (DIMACS)")
    pg.add_argument("--vars", type=int, default=30)
    pg.add_argument("--ratio", type=float, default=4.3)
    pg.add_argument("--seed", type=int, default=1)
    pg.set_defaults(func=cmd_gen)

    pw = sub.add_parser("sweep", help="sweep the 3-SAT phase transition")
    pw.add_argument("--vars", type=int, default=60)
    pw.add_argument("--samples", type=int, default=20, help="instances per ratio")
    pw.add_argument("--seed", type=int, default=1)
    pw.set_defaults(func=cmd_sweep)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
