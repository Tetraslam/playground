from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from random import Random
from types import ModuleType

DIRECTIONS = ((1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1))
ACTION_KINDS = frozenset({"rest", "move", "eat", "attack", "bud"})


@dataclass(frozen=True, slots=True)
class Action:
    kind: str
    direction: int = 0

    def __post_init__(self) -> None:
        if self.kind not in ACTION_KINDS:
            raise ValueError(f"unknown action: {self.kind}")
        if not 0 <= self.direction < 6:
            raise ValueError(f"direction must be 0..5, got {self.direction}")


@dataclass(frozen=True, slots=True)
class CellView:
    resource: int
    faction: str | None
    energy: int


@dataclass(frozen=True, slots=True)
class View:
    here: CellView
    neighbors: tuple[CellView, ...]
    energy: int
    age: int
    tick: int


@dataclass(slots=True)
class Organism:
    id: int
    faction: str
    q: int
    r: int
    energy: int = 28
    age: int = 0


@dataclass(frozen=True, slots=True)
class Faction:
    name: str
    glyph: str
    color: tuple[int, int, int]
    module: ModuleType


class World:
    def __init__(
        self,
        width: int,
        height: int,
        factions: list[Faction],
        *,
        seed: int = 6,
        initial_per_faction: int = 12,
    ) -> None:
        if width < 4 or height < 4:
            raise ValueError("world must be at least 4x4")
        if not factions:
            raise ValueError("at least one faction is required")
        if initial_per_faction * len(factions) > width * height:
            raise ValueError("too many initial organisms for the grid")

        self.width = width
        self.height = height
        self.factions = {f.name: f for f in factions}
        self.seed = seed
        self.rng = Random(seed)
        self.tick = 0
        self.next_id = 1
        self.resources = [self.rng.randrange(2, 11) for _ in range(width * height)]
        self.organisms: dict[int, Organism] = {}

        cells = [(q, r) for r in range(height) for q in range(width)]
        self.rng.shuffle(cells)
        for faction in factions:
            for _ in range(initial_per_faction):
                q, r = cells.pop()
                self._spawn(faction.name, q, r)

    def _index(self, q: int, r: int) -> int:
        return (r % self.height) * self.width + (q % self.width)

    def neighbor(self, q: int, r: int, direction: int) -> tuple[int, int]:
        dq, dr = DIRECTIONS[direction]
        return (q + dq) % self.width, (r + dr) % self.height

    def _spawn(self, faction: str, q: int, r: int, energy: int = 28) -> Organism:
        organism = Organism(self.next_id, faction, q, r, energy)
        self.organisms[organism.id] = organism
        self.next_id += 1
        return organism

    def _cell_view(self, q: int, r: int, occupancy: dict[tuple[int, int], Organism]) -> CellView:
        other = occupancy.get((q, r))
        return CellView(
            self.resources[self._index(q, r)],
            other.faction if other else None,
            other.energy if other else 0,
        )

    def _view(self, organism: Organism, occupancy: dict[tuple[int, int], Organism]) -> View:
        cells = tuple(
            self._cell_view(*self.neighbor(organism.q, organism.r, direction), occupancy)
            for direction in range(6)
        )
        return View(
            self._cell_view(organism.q, organism.r, occupancy),
            cells,
            organism.energy,
            organism.age,
            self.tick,
        )

    def step(self) -> None:
        # Policies observe one immutable snapshot. Resolution order below is part
        # of the engine contract and never depends on dictionary insertion order.
        ordered = sorted(self.organisms.values(), key=lambda organism: organism.id)
        occupancy = {(organism.q, organism.r): organism for organism in ordered}
        actions: dict[int, Action] = {}
        for organism in ordered:
            policy = self.factions[organism.faction].module.decide
            action = policy(self._view(organism, occupancy), self.rng)
            if not isinstance(action, Action):
                raise TypeError(f"{organism.faction}.decide must return Action")
            actions[organism.id] = action

        damage: Counter[int] = Counter()
        for organism in ordered:
            action = actions[organism.id]
            if action.kind != "attack" or organism.energy < 4:
                continue
            target_pos = self.neighbor(organism.q, organism.r, action.direction)
            target = occupancy.get(target_pos)
            if target and target.faction != organism.faction:
                damage[target.id] += 9
                organism.energy -= 3
        for target_id, amount in damage.items():
            if target_id in self.organisms:
                self.organisms[target_id].energy -= amount

        self._remove_dead()

        eaters: defaultdict[int, list[Organism]] = defaultdict(list)
        for organism in ordered:
            if organism.id not in self.organisms:
                continue
            action = actions[organism.id]
            if action.kind == "eat":
                q, r = self.neighbor(organism.q, organism.r, action.direction)
                eaters[self._index(q, r)].append(organism)
        for cell_index, claimants in eaters.items():
            available = self.resources[cell_index]
            for organism in sorted(claimants, key=lambda item: (-item.energy, item.id)):
                taken = min(7, available)
                organism.energy += taken
                available -= taken
                if available == 0:
                    break
            self.resources[cell_index] = available

        # Movement and budding can only claim cells empty in the original
        # snapshot. Highest energy wins a collision, then lowest stable id.
        claims: defaultdict[tuple[int, int], list[tuple[Organism, str]]] = defaultdict(list)
        for organism in ordered:
            if organism.id not in self.organisms:
                continue
            action = actions[organism.id]
            if action.kind not in {"move", "bud"}:
                continue
            target = self.neighbor(organism.q, organism.r, action.direction)
            if target in occupancy:
                continue
            if action.kind == "bud" and organism.energy < 34:
                continue
            claims[target].append((organism, action.kind))

        for (q, r), contenders in sorted(claims.items()):
            organism, kind = min(contenders, key=lambda item: (-item[0].energy, item[0].id))
            if kind == "move":
                organism.q, organism.r = q, r
                organism.energy -= 2
            else:
                child_energy = organism.energy // 2
                organism.energy -= child_energy + 2
                self._spawn(organism.faction, q, r, child_energy)

        for organism in self.organisms.values():
            organism.energy -= 1
            organism.age += 1
        self._remove_dead()

        for index, resource in enumerate(self.resources):
            if resource < 18 and self.rng.random() < 0.16:
                self.resources[index] += 1
        self.tick += 1
        self.assert_invariants()

    def _remove_dead(self) -> None:
        for organism_id, organism in list(self.organisms.items()):
            if organism.energy <= 0 or organism.age >= 500:
                self.resources[self._index(organism.q, organism.r)] = min(
                    18, self.resources[self._index(organism.q, organism.r)] + 5
                )
                del self.organisms[organism_id]

    def populations(self) -> Counter[str]:
        return Counter(organism.faction for organism in self.organisms.values())

    def assert_invariants(self) -> None:
        positions = [(organism.q, organism.r) for organism in self.organisms.values()]
        assert len(positions) == len(set(positions)), "two organisms share a cell"
        assert all(0 <= q < self.width and 0 <= r < self.height for q, r in positions)
        assert all(organism.energy > 0 for organism in self.organisms.values())
        assert all(0 <= resource <= 18 for resource in self.resources)
