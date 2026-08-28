from engine import Action, View

NAME = "stormfinch"
GLYPH = "s"
COLOR = (116, 172, 255)


def decide(view: View, rng) -> Action:
    enemies = [
        (cell.energy, direction)
        for direction, cell in enumerate(view.neighbors)
        if cell.faction not in {None, NAME}
    ]
    kin = sum(cell.faction == NAME for cell in view.neighbors)
    if enemies and (kin >= 1 or len(enemies) >= 2) and view.energy >= 14:
        weakest = min(energy for energy, _ in enemies)
        targets = [direction for energy, direction in enemies if energy == weakest]
        return Action("attack", rng.choice(targets))

    open_cells = [
        (cell.resource, direction)
        for direction, cell in enumerate(view.neighbors)
        if cell.faction is None
    ]
    if view.energy >= 38 and open_cells:
        richest = max(resource for resource, _ in open_cells)
        frontiers = [direction for resource, direction in open_cells if resource == richest]
        return Action("bud", rng.choice(frontiers))

    forage = [
        (cell.resource, direction)
        for direction, cell in enumerate(view.neighbors)
        if cell.faction != NAME
    ]
    if forage:
        richest = max(resource for resource, _ in forage)
        if richest >= 5 and (view.energy <= 36 or richest >= 9 or kin >= 2):
            patches = [direction for resource, direction in forage if resource == richest]
            return Action("eat", rng.choice(patches))

    if open_cells:
        prevailing = (view.tick // 18) % 6
        by_direction = {direction: resource for resource, direction in open_cells}
        if prevailing in by_direction and by_direction[prevailing] >= 2:
            return Action("move", prevailing)

        richest = max(resource for resource, _ in open_cells)
        frontiers = [direction for resource, direction in open_cells if resource == richest]
        return Action("move", rng.choice(frontiers))

    if forage and view.energy < 28:
        richest = max(resource for resource, _ in forage)
        patches = [direction for resource, direction in forage if resource == richest]
        return Action("eat", rng.choice(patches))
    return Action("rest")
