from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).parent))

from engine import Action, Faction, View, World  # noqa: E402


def faction(name: str, decide) -> Faction:
    module = ModuleType(name)
    module.decide = decide
    return Faction(name, name[0], (180, 180, 180), module)


def grazer(view: View, rng: random.Random) -> Action:
    open_directions = [
        direction for direction, cell in enumerate(view.neighbors) if cell.faction is None
    ]
    if view.energy >= 40 and open_directions:
        return Action("bud", rng.choice(open_directions))
    richest = max(range(6), key=lambda direction: view.neighbors[direction].resource)
    if view.neighbors[richest].resource:
        return Action("eat", richest)
    return Action("move", rng.randrange(6))


def wanderer(view: View, rng: random.Random) -> Action:
    enemies = [
        direction
        for direction, cell in enumerate(view.neighbors)
        if cell.faction not in {None, "wanderer"}
    ]
    if enemies:
        return Action("attack", rng.choice(enemies))
    return Action("move", rng.randrange(6))


def snapshot(world: World) -> tuple:
    organisms = tuple(
        (item.id, item.faction, item.q, item.r, item.energy, item.age)
        for item in sorted(world.organisms.values(), key=lambda item: item.id)
    )
    return world.tick, tuple(world.resources), organisms


class WorldTests(unittest.TestCase):
    def test_replay_is_deterministic(self) -> None:
        factions = [faction("grazer", grazer), faction("wanderer", wanderer)]
        left = World(18, 12, factions, seed=42, initial_per_faction=8)
        right = World(18, 12, factions, seed=42, initial_per_faction=8)

        for _ in range(250):
            left.step()
            right.step()

        self.assertEqual(snapshot(left), snapshot(right))

    def test_higher_energy_organism_wins_shared_move_target(self) -> None:
        east = faction("east", lambda view, rng: Action("move", 0))
        west = faction("west", lambda view, rng: Action("move", 3))
        world = World(6, 6, [east, west], seed=1, initial_per_faction=0)
        weaker = world._spawn("east", 0, 0, energy=20)
        stronger = world._spawn("west", 2, 0, energy=30)

        world.step()

        self.assertEqual((weaker.q, weaker.r), (0, 0))
        self.assertEqual((stronger.q, stronger.r), (1, 0))
        self.assertEqual(len({(item.q, item.r) for item in world.organisms.values()}), 2)

    def test_long_run_preserves_world_invariants(self) -> None:
        factions = [faction("grazer", grazer), faction("wanderer", wanderer)]
        world = World(30, 18, factions, seed=6, initial_per_faction=20)

        for _ in range(1_000):
            if not world.organisms:
                break
            world.step()
            world.assert_invariants()

        self.assertGreater(world.tick, 20)


if __name__ == "__main__":
    unittest.main()
