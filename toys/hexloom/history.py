from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

from engine import World
from main import load_factions


def render_history(world: World, history: list[dict[str, int]]) -> str:
    width, height = 1200, 820
    chart_x, chart_y, chart_w, chart_h = 70, 120, 1060, 270
    names = sorted(world.factions)
    peak = max((count for sample in history for count in sample.values()), default=1)
    peak = max(peak, 1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "<style>text{font-family:ui-monospace,monospace}"
        ".label{fill:#9aa8bd;font-size:13px}.title{fill:#e8eef8;font-size:28px;font-weight:700}"
        ".grid{stroke:#273248;stroke-width:1}.line{fill:none;stroke-width:3}</style>",
        '<rect width="100%" height="100%" fill="#0b101b"/>',
        f'<text class="title" x="{chart_x}" y="55">HEXLOOM / SEED {world.seed}</text>',
        f'<text class="label" x="{chart_x}" y="82">{world.tick} synchronous ticks · '
        f"{world.width}×{world.height} toroidal field</text>",
    ]

    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = chart_y + chart_h * (1 - fraction)
        value = round(peak * fraction)
        parts.append(
            f'<line class="grid" x1="{chart_x}" y1="{y:.1f}" '
            f'x2="{chart_x + chart_w}" y2="{y:.1f}"/>'
        )
        parts.append(f'<text class="label" x="30" y="{y + 4:.1f}">{value}</text>')

    span = max(len(history) - 1, 1)
    for name in names:
        faction = world.factions[name]
        color = f"rgb{faction.color}"
        points = " ".join(
            f"{chart_x + chart_w * index / span:.1f},"
            f"{chart_y + chart_h * (1 - sample.get(name, 0) / peak):.1f}"
            for index, sample in enumerate(history)
        )
        parts.append(f'<polyline class="line" stroke="{color}" points="{points}"/>')

    legend_y = 425
    for index, name in enumerate(names):
        faction = world.factions[name]
        x = chart_x + index * 250
        count = world.populations().get(name, 0)
        parts.append(f'<circle cx="{x}" cy="{legend_y}" r="6" fill="rgb{faction.color}"/>')
        parts.append(
            f'<text class="label" x="{x + 14}" y="{legend_y + 5}">{escape(name)} {count}</text>'
        )

    map_x, map_y, map_w, map_h = 70, 470, 1060, 290
    x_step = map_w / (world.width + 0.5)
    y_step = map_h / max(world.height - 0.5, 1)
    radius = max(1.5, min(x_step, y_step) * 0.34)
    occupied = {(organism.q, organism.r): organism for organism in world.organisms.values()}
    for r in range(world.height):
        for q in range(world.width):
            x = map_x + (q + 0.5 + 0.5 * (r % 2)) * x_step
            y = map_y + (r + 0.5) * y_step
            resource = world.resources[r * world.width + q]
            shade = 20 + round(resource / 18 * 65)
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
                f'fill="rgb({shade - 4},{shade},{shade + 12})"/>'
            )
            organism = occupied.get((q, r))
            if organism:
                color = world.factions[organism.faction].color
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius * 0.72:.1f}" fill="rgb{color}"/>'
                )

    parts.append(
        f'<text class="label" x="{map_x}" y="800">population trajectories / final resource field</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="export a Hexloom run as an SVG history")
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--seed", type=int, default=6)
    parser.add_argument("--width", type=int, default=36)
    parser.add_argument("--height", type=int, default=18)
    parser.add_argument("--initial", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    world = World(
        args.width,
        args.height,
        load_factions(),
        seed=args.seed,
        initial_per_faction=args.initial,
    )
    history = [dict(world.populations())]
    for _ in range(args.steps):
        if not world.organisms:
            break
        world.step()
        history.append(dict(world.populations()))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_history(world, history), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
