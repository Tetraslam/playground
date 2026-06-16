"""Tournament runner and reporting."""

import csv
from collections import defaultdict
from itertools import combinations

from .engine import play_match
from .strategies import Strategy


def run_tournament(
    strategies: list[type[Strategy]],
    rounds: int = 200,
    repetitions: int = 5,
    noise: float = 0.0,
    seed: int = 0,
    include_self: bool = True,
) -> dict[str, dict[str, tuple[int, int]]]:
    """Round-robin tournament. Returns scores per pair, averaged over repetitions."""
    results: dict[tuple[str, str], tuple[int, int]] = defaultdict(lambda: (0, 0))

    for rep in range(repetitions):
        pairs = list(combinations(strategies, 2))
        if include_self:
            pairs += [(s, s) for s in strategies]
        for sa, sb in pairs:
            a, b, _, _ = play_match(
                sa,
                sb,
                rounds=rounds,
                noise=noise,
                seed=seed + rep,
            )
            prev = results[(sa.name, sb.name)]
            results[(sa.name, sb.name)] = (prev[0] + a, prev[1] + b)

    avg: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
    for (na, nb), (score_a, score_b) in results.items():
        avg[na][nb] = (round(score_a / repetitions), round(score_b / repetitions))
    return avg


def standings(
    results: dict[str, dict[str, tuple[int, int]]],
    strategies: list[type[Strategy]],
) -> list[dict[str, object]]:
    rows = []
    for s in strategies:
        name = s.name
        total = 0
        wins = 0
        losses = 0
        for _opponent, (my, their) in results.get(name, {}).items():
            total += my
            if my > their:
                wins += 1
            elif my < their:
                losses += 1
        rows.append(
            {
                "rank": 0,
                "strategy": name,
                "total": total,
                "wins": wins,
                "losses": losses,
            }
        )
    rows.sort(key=lambda r: r["total"], reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def print_table(rows: list[dict[str, object]]) -> None:
    widths = {
        "rank": 4,
        "strategy": max(len(str(r["strategy"])) for r in rows) if rows else 8,
        "total": max(len(str(r["total"])) for r in rows) if rows else 5,
        "wins": 4,
        "losses": 4,
    }
    header = (
        f"{'#':>{widths['rank']}}  "
        f"{'strategy':<{widths['strategy']}}  "
        f"{'total':>{widths['total']}}  "
        f"{'wins':>{widths['wins']}}  "
        f"{'losses':>{widths['losses']}}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['rank']:>{widths['rank']}}  "
            f"{r['strategy']:<{widths['strategy']}}  "
            f"{r['total']:>{widths['total']}}  "
            f"{r['wins']:>{widths['wins']}}  "
            f"{r['losses']:>{widths['losses']}}"
        )


def write_csv(
    path: str,
    rows: list[dict[str, object]],
    details: dict[str, dict[str, tuple[int, int]]],
) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "strategy", "total", "wins", "losses"])
        for r in rows:
            writer.writerow([r["rank"], r["strategy"], r["total"], r["wins"], r["losses"]])

        writer.writerow([])
        writer.writerow(["strategy", "opponent", "my_score", "their_score"])
        for strategy, opponents in details.items():
            for opponent, (my, their) in opponents.items():
                writer.writerow([strategy, opponent, my, their])
