"""coreloom: run a Core War round-robin over warriors/*.red and print the scoreboard.

uv run python toys/coreloom/main.py --rounds 50 --seed 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import tournament  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="coreloom", description=__doc__.splitlines()[0])
    p.add_argument("--rounds", type=int, default=50, help="rounds per pairing (default 50)")
    p.add_argument("--seed", type=int, default=1, help="master seed (default 1)")
    p.add_argument("--max-cycles", type=int, default=80_000, help="cycles before a round ties")
    p.add_argument(
        "--warriors",
        type=Path,
        default=tournament.WARRIOR_DIR,
        help="directory of .red files (default toys/coreloom/warriors)",
    )
    p.add_argument("--only", nargs="+", metavar="NAME", help="restrict to these warrior file stems")
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=os.cpu_count() or 1,
        help="worker processes (results are identical for any value)",
    )
    p.add_argument("--json", type=Path, metavar="FILE", help="also write results as JSON")
    p.add_argument("-q", "--quiet", action="store_true", help="no progress line")
    args = p.parse_args(argv)

    warriors = tournament.load_warriors(args.warriors, args.only)
    if len(warriors) < 2:
        print(
            f"need at least 2 warriors in {args.warriors}, found {len(warriors)}", file=sys.stderr
        )
        return 1

    def progress(done: int, total: int) -> None:
        if not args.quiet and sys.stderr.isatty():
            print(
                f"\r{done}/{total} rounds",
                end="" if done < total else "\n",
                file=sys.stderr,
                flush=True,
            )

    t0 = time.perf_counter()
    board = tournament.play(
        warriors,
        args.rounds,
        args.seed,
        max_cycles=args.max_cycles,
        jobs=args.jobs,
        progress=progress,
    )
    elapsed = time.perf_counter() - t0

    print(board.render())
    if not args.quiet:
        print(f"\n{elapsed:.1f}s", file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps(board.to_json(), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
