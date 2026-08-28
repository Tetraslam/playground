from engine import Action, View

NAME = "tideglass"
GLYPH = "t"
COLOR = (80, 205, 220)


def decide(view: View, rng) -> Action:
    """Move as one tide, pausing together to feed and reproduce."""
    open_directions = [
        direction for direction, cell in enumerate(view.neighbors) if cell.faction is None
    ]
    enemies = [
        direction
        for direction, cell in enumerate(view.neighbors)
        if cell.faction not in {None, NAME}
    ]

    # Every organism sees the same clock. The synchronized phase turns a set of
    # memoryless local policies into one migrating, six-direction crystal.
    phase = view.tick % 12
    tide_direction = (view.tick // 12) % 6

    # A tide pool closes ranks immediately when another faction touches it;
    # without this reflex, synchronized cohorts are picked apart one by one.
    if enemies and view.energy >= 16:
        return Action("attack", rng.choice(enemies))

    rich_cells = [
        (cell.resource, direction)
        for direction, cell in enumerate(view.neighbors)
        if cell.resource > 0
    ]
    if (phase >= 6 or view.energy < 25) and rich_cells:
        return Action("eat", max(rich_cells)[1])

    if phase == 5 and view.energy >= 40 and open_directions:
        return Action("bud", min(open_directions, key=lambda d: (d - tide_direction) % 6))

    if tide_direction in open_directions:
        return Action("move", tide_direction)
    if open_directions:
        return Action("move", min(open_directions, key=lambda d: (d - tide_direction) % 6))
    return Action("rest")
