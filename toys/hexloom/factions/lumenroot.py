from engine import Action, View

NAME = "lumenroot"
GLYPH = "l"
COLOR = (238, 210, 110)


def decide(view: View, rng) -> Action:
    kin = [direction for direction, cell in enumerate(view.neighbors) if cell.faction == NAME]
    open_cells = [
        (cell.resource, direction)
        for direction, cell in enumerate(view.neighbors)
        if cell.faction is None
    ]
    food = [
        (cell.resource, direction)
        for direction, cell in enumerate(view.neighbors)
        if cell.resource > 0
    ]
    enemies = [
        (cell.energy, direction)
        for direction, cell in enumerate(view.neighbors)
        if cell.faction not in {None, NAME}
    ]

    if enemies and view.energy >= (16 if kin else 28):
        weakest = min(energy for energy, _ in enemies)
        return Action(
            "attack",
            rng.choice([direction for energy, direction in enemies if energy == weakest]),
        )

    budding_energy = 34 if kin else 38
    if view.energy >= budding_energy and open_cells:
        return Action("bud", _richest(open_cells, rng))

    if food and (view.energy < 42 or kin):
        return Action("eat", _richest(food, rng))

    if not kin and open_cells:
        return Action("move", _richest(open_cells, rng))

    return Action("rest")


def _richest(cells: list[tuple[int, int]], rng) -> int:
    best = max(resource for resource, _ in cells)
    return rng.choice([direction for resource, direction in cells if resource == best])
