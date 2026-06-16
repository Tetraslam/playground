"""CLI entrypoint for the dilemma tournament."""

import argparse
import sys

from .strategies import NAME_TO_STRATEGY
from .tournament import print_table, run_tournament, standings, write_csv


def _parse_strategy_list(s: str | None) -> list:
    if not s:
        return list(NAME_TO_STRATEGY.values())
    names = [name.strip() for name in s.split(",")]
    missing = [name for name in names if name not in NAME_TO_STRATEGY]
    if missing:
        print(f"unknown strategies: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    return [NAME_TO_STRATEGY[name] for name in names]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run an iterated Prisoner's Dilemma tournament.")
    parser.add_argument(
        "-s",
        "--strategies",
        help="comma-separated strategy names (default: all)",
    )
    parser.add_argument(
        "-r",
        "--rounds",
        type=int,
        default=200,
        help="rounds per match (default: 200)",
    )
    parser.add_argument(
        "-n",
        "--reps",
        type=int,
        default=5,
        help="repetitions per pairing (default: 5)",
    )
    parser.add_argument(
        "--noise",
        type=float,
        default=0.0,
        help="probability of a move being flipped (default: 0.0)",
    )
    parser.add_argument(
        "--no-self",
        action="store_true",
        help="exclude mirror matches (default: include them)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="base random seed (default: 0)",
    )
    parser.add_argument(
        "-o",
        "--out",
        help="write results to CSV file",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list built-in strategies and exit",
    )
    args = parser.parse_args(argv)

    if args.list:
        print("built-in strategies:")
        for name in sorted(NAME_TO_STRATEGY):
            print(f"  {name}")
        return

    strategies = _parse_strategy_list(args.strategies)
    if len(strategies) < 2:
        print("need at least two strategies", file=sys.stderr)
        sys.exit(1)

    results = run_tournament(
        strategies,
        rounds=args.rounds,
        repetitions=args.reps,
        noise=args.noise,
        seed=args.seed,
        include_self=not args.no_self,
    )
    rows = standings(results, strategies)
    print_table(rows)

    if args.out:
        write_csv(args.out, rows, results)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
