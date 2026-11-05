"""Tournament bookkeeping tests, run against a stub VM so they don't depend on vm.py semantics.

uv run python -m unittest toys/coreloom/test_tournament.py
"""

import random
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import tournament  # noqa: E402


class W:
    def __init__(self, name):
        self.name = name


def first_mover_wins(warriors, seed, max_cycles):
    return 0


def by_name(winner_name):
    def run(warriors, seed, max_cycles):
        names = [w.name for w in warriors]
        return names.index(winner_name) if winner_name in names else None

    return run


def coin(warriors, seed, max_cycles):
    r = random.Random(seed).random()
    return None if r < 0.2 else int(r >= 0.6)


class TournamentTest(unittest.TestCase):
    def setUp(self):
        self.real_vm = tournament.vm
        tournament.vm = types.SimpleNamespace()

    def tearDown(self):
        tournament.vm = self.real_vm

    def test_first_mover_advantage_is_cancelled(self):
        tournament.vm.run_round = first_mover_wins
        board = tournament.play([W("a"), W("b")], rounds=10, seed=1)
        self.assertEqual(board.totals["a"].wins, 5)
        self.assertEqual(board.totals["b"].wins, 5)

    def test_winner_maps_back_to_the_right_warrior(self):
        tournament.vm.run_round = by_name("b")
        board = tournament.play([W("a"), W("b"), W("c")], rounds=4, seed=1)
        self.assertEqual(board.ranking()[0][0], "b")
        self.assertEqual(board.pairs[("b", "a")].wins, 4)
        self.assertEqual(board.pairs[("a", "c")].ties, 4)
        self.assertEqual(board.score("b"), 3.0)

    def test_deterministic_and_stable_under_new_entrants(self):
        tournament.vm.run_round = coin
        small = tournament.play([W("a"), W("b")], rounds=30, seed=7)
        again = tournament.play([W("a"), W("b")], rounds=30, seed=7)
        big = tournament.play([W("a"), W("b"), W("c")], rounds=30, seed=7)
        self.assertEqual(small.to_json(), again.to_json())
        self.assertEqual(small.pairs[("a", "b")], big.pairs[("a", "b")])

    def test_points_are_conserved(self):
        tournament.vm.run_round = coin
        board = tournament.play([W(n) for n in "abcd"], rounds=25, seed=3)
        played = sum(r.played for r in board.totals.values())
        self.assertEqual(played, 2 * 6 * 25)
        self.assertEqual(
            sum(r.wins for r in board.totals.values()), sum(r.losses for r in board.totals.values())
        )

    def test_score_vs_only_fights_the_candidate(self):
        calls = []

        def run(warriors, seed, max_cycles):
            calls.append({w.name for w in warriors})
            return None

        tournament.vm.run_round = run
        tournament.score_vs(W("x"), [W("h1"), W("h2")], rounds=3, seed=1)
        self.assertEqual(len(calls), 6)
        self.assertTrue(all("x" in c for c in calls))

    def test_duplicate_names_rejected(self):
        with self.assertRaises(ValueError):
            tournament.play([W("a"), W("a")], rounds=1, seed=1)


if __name__ == "__main__":
    unittest.main()
