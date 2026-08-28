from engine import Action, View

NAME = "mycelium"
GLYPH = "m"
COLOR = (104, 211, 145)


def decide(view: View, rng) -> Action:
    enemies = [
        direction
        for direction, cell in enumerate(view.neighbors)
        if cell.faction not in {None, NAME}
    ]
    kin = sum(cell.faction == NAME for cell in view.neighbors)
    if enemies and kin >= 1 and view.energy >= 30:
        return Action("attack", rng.choice(enemies))

    open_cells = [
        (cell.resource, direction)
        for direction, cell in enumerate(view.neighbors)
        if cell.faction is None
    ]
    if view.energy >= 42 and open_cells:
        return Action("bud", max(open_cells)[1])

    richest, direction = max(
        ((cell.resource, direction) for direction, cell in enumerate(view.neighbors)),
        default=(0, 0),
    )
    if richest >= 5 and view.energy < 38:
        return Action("eat", direction)
    if open_cells:
        return Action("move", max(open_cells)[1])
    return Action("rest")
