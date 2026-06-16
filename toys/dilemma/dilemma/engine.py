"""Iterated Prisoner's Dilemma tournament."""

PAYOFFS = {
    ("C", "C"): (3, 3),
    ("C", "D"): (0, 5),
    ("D", "C"): (5, 0),
    ("D", "D"): (1, 1),
}


def play_round(move_a: str, move_b: str) -> tuple[int, int]:
    """Return scores for (A, B) given their moves."""
    return PAYOFFS[(move_a, move_b)]


def play_match(strategy_a, strategy_b, rounds: int = 200, noise: float = 0.0, seed=0):
    """Play two strategies against each other."""
    from random import Random

    rng = Random(seed)
    a, b = strategy_a(), strategy_b()
    history_a: list[str] = []
    history_b: list[str] = []
    score_a = score_b = 0

    for _ in range(rounds):
        move_a = a.move(history_a, history_b)
        move_b = b.move(history_b, history_a)
        if noise and rng.random() < noise:
            move_a = "D" if move_a == "C" else "C"
        if noise and rng.random() < noise:
            move_b = "D" if move_b == "C" else "C"
        history_a.append(move_a)
        history_b.append(move_b)
        sa, sb = play_round(move_a, move_b)
        score_a += sa
        score_b += sb

    return score_a, score_b, history_a, history_b
