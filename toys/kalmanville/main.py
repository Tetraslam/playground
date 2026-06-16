"""kalmanville: noisy city sensors filtered into a tiny world model.

The toy draws a generated street grid, simulates transit vehicles moving through
it, corrupts their GPS pings with urban-canyon noise, runs a constant-velocity
Kalman filter, then projects a short forecast from the final filtered state.

    uv run python toys/kalmanville/main.py --seed morning --out scratch/morning.svg
    uv run python toys/kalmanville/main.py --seed storm --noise 34

Stdlib only. Same seed and options produce the same city.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
from dataclasses import dataclass
from pathlib import Path


class Rng:
    """Deterministic splitmix64 PRNG seeded from a string."""

    def __init__(self, seed: str):
        self.s = int.from_bytes(hashlib.blake2b(seed.encode(), digest_size=8).digest(), "little")

    def _next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def rand(self) -> float:
        return (self._next() >> 11) / float(1 << 53)

    def randint(self, a: int, b: int) -> int:
        return a + int(self.rand() * (b - a + 1))

    def gauss(self) -> float:
        u1 = max(1e-9, self.rand())
        u2 = self.rand()
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


@dataclass(frozen=True)
class Pt:
    x: float
    y: float


@dataclass(frozen=True)
class Block:
    x: float
    y: float
    w: float
    h: float
    fill: str
    kind: str
    height: float


@dataclass(frozen=True)
class City:
    size: int
    xs: list[float]
    ys: list[float]
    blocks: list[Block]
    center: Pt


@dataclass(frozen=True)
class RouteSpec:
    name: str
    color: str
    path: list[Pt]
    loop: bool
    phase: float
    speed: float


@dataclass(frozen=True)
class Run:
    spec: RouteSpec
    truth: list[Pt]
    observations: list[Pt | None]
    estimates: list[Pt]
    forecast: list[Pt]
    forecast_radius: list[float]
    noisy_rmse: float
    filter_rmse: float
    pings: int


class Kalman1D:
    """Constant-velocity Kalman filter for one coordinate."""

    def __init__(self, pos: float, vel: float = 0.0):
        self.pos = pos
        self.vel = vel
        self.p00 = 400.0
        self.p01 = 0.0
        self.p10 = 0.0
        self.p11 = 100.0

    def copy(self) -> Kalman1D:
        other = Kalman1D(self.pos, self.vel)
        other.p00 = self.p00
        other.p01 = self.p01
        other.p10 = self.p10
        other.p11 = self.p11
        return other

    def predict(self, dt: float, process_var: float = 6.0) -> None:
        self.pos += self.vel * dt

        p00 = self.p00 + dt * (self.p10 + self.p01) + dt * dt * self.p11
        p01 = self.p01 + dt * self.p11
        p10 = self.p10 + dt * self.p11
        p11 = self.p11

        q00 = process_var * dt**4 / 4
        q01 = process_var * dt**3 / 2
        q11 = process_var * dt**2
        self.p00 = p00 + q00
        self.p01 = p01 + q01
        self.p10 = p10 + q01
        self.p11 = p11 + q11

    def update(self, measurement: float, measurement_var: float) -> None:
        innovation = measurement - self.pos
        residual_var = self.p00 + measurement_var
        k0 = self.p00 / residual_var
        k1 = self.p10 / residual_var

        old_p00 = self.p00
        old_p01 = self.p01
        old_p10 = self.p10
        old_p11 = self.p11

        self.pos += k0 * innovation
        self.vel += k1 * innovation
        self.p00 = (1 - k0) * old_p00
        self.p01 = (1 - k0) * old_p01
        self.p10 = old_p10 - k1 * old_p00
        self.p11 = old_p11 - k1 * old_p01


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def dist(a: Pt, b: Pt) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_city(seed: str, size: int) -> City:
    rng = Rng(f"city:{seed}:{size}")
    left = size * 0.08
    right = size * 0.92
    top = size * 0.20
    bottom = size * 0.90
    cols = 9
    rows = 7
    xs = [lerp(left, right, i / (cols - 1)) for i in range(cols)]
    ys = [lerp(top, bottom, i / (rows - 1)) for i in range(rows)]
    center = Pt((left + right) / 2, (top + bottom) / 2)
    blocks: list[Block] = []

    for yi in range(rows - 1):
        for xi in range(cols - 1):
            x0 = xs[xi]
            x1 = xs[xi + 1]
            y0 = ys[yi]
            y1 = ys[yi + 1]
            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            dx = (cx - center.x) / (right - left)
            dy = (cy - center.y) / (bottom - top)
            downtown = math.exp(-((dx / 0.23) ** 2 + (dy / 0.27) ** 2))
            roll = rng.rand()

            if roll < 0.07:
                fill, kind = "#173d31", "park"
            elif roll < 0.11:
                fill, kind = "#14314b", "water"
            elif downtown > 0.45:
                fill, kind = "#1f2945", "canyon"
            elif roll < 0.32:
                fill, kind = "#283044", "civic"
            else:
                fill, kind = "#20283a", "residential"

            blocks.append(
                Block(
                    x=x0 + 5,
                    y=y0 + 5,
                    w=(x1 - x0) - 10,
                    h=(y1 - y0) - 10,
                    fill=fill,
                    kind=kind,
                    height=downtown,
                )
            )

    return City(size=size, xs=xs, ys=ys, blocks=blocks, center=center)


def grid_pt(city: City, col: int, row: int) -> Pt:
    return Pt(city.xs[col], city.ys[row])


def make_routes(city: City, seed: str) -> list[RouteSpec]:
    rng = Rng(f"routes:{seed}")
    max_col = len(city.xs) - 1
    max_row = len(city.ys) - 1
    colors = ["#5eead4", "#f97316", "#a78bfa", "#facc15"]

    r1 = rng.randint(1, max_row - 1)
    r2 = rng.randint(1, max_row - 1)
    c1 = rng.randint(2, max_col - 2)
    c2 = rng.randint(2, max_col - 2)
    while r2 == r1:
        r2 = rng.randint(1, max_row - 1)
    while c2 == c1:
        c2 = rng.randint(2, max_col - 2)

    specs = [
        (
            "crosstown",
            colors[0],
            [(0, r1), (c1, r1), (c1, r2), (max_col, r2)],
            False,
        ),
        (
            "northline",
            colors[1],
            [(c2, 0), (c2, 2), (max_col - c2, 2), (max_col - c2, max_row)],
            False,
        ),
        (
            "riverbend",
            colors[2],
            [(0, max_row - 1), (2, max_row - 1), (2, 3), (5, 3), (5, 1), (max_col, 1)],
            False,
        ),
        (
            "downtown loop",
            colors[3],
            [(3, 2), (6, 2), (6, 4), (3, 4)],
            True,
        ),
    ]

    routes: list[RouteSpec] = []
    for name, color, idx_path, loop in specs:
        path = [grid_pt(city, col, row) for col, row in idx_path]
        if loop:
            path = [*path, path[0]]
        routes.append(
            RouteSpec(
                name=name,
                color=color,
                path=path,
                loop=loop,
                phase=rng.rand() * 0.45,
                speed=0.82 + rng.rand() * 0.42,
            )
        )
    return routes


def point_on_path(path: list[Pt], t: float) -> Pt:
    segments = [(a, b, dist(a, b)) for a, b in zip(path, path[1:], strict=False)]
    total = sum(length for _, _, length in segments)
    if total <= 0:
        return path[0]

    target = clamp(t, 0.0, 1.0) * total
    walked = 0.0
    for a, b, length in segments:
        if walked + length >= target:
            local = 0.0 if length == 0 else (target - walked) / length
            return Pt(lerp(a.x, b.x, local), lerp(a.y, b.y, local))
        walked += length
    return path[-1]


def canyon_strength(city: City, p: Pt) -> float:
    width = city.xs[-1] - city.xs[0]
    height = city.ys[-1] - city.ys[0]
    dx = (p.x - city.center.x) / (width * 0.24)
    dy = (p.y - city.center.y) / (height * 0.30)
    return math.exp(-(dx * dx + dy * dy))


def noisy_ping(
    rng: Rng, city: City, p: Pt, base_noise: float, step: int
) -> tuple[Pt | None, float]:
    canyon = canyon_strength(city, p)
    sigma = base_noise * (0.55 + 1.65 * canyon)
    if step > 0 and rng.rand() < 0.025 + 0.075 * canyon:
        return None, sigma

    outlier = 3.3 if step > 0 and rng.rand() < 0.025 + 0.035 * canyon else 1.0
    return Pt(p.x + rng.gauss() * sigma * outlier, p.y + rng.gauss() * sigma * outlier), sigma


def simulate_route(city: City, spec: RouteSpec, seed: str, steps: int, base_noise: float) -> Run:
    rng = Rng(f"sim:{seed}:{spec.name}:{steps}:{base_noise}")
    truth: list[Pt] = []
    observations: list[Pt | None] = []
    estimates: list[Pt] = []

    start = point_on_path(spec.path, spec.phase % 1.0)
    kx = Kalman1D(start.x)
    ky = Kalman1D(start.y)
    noisy_errors: list[float] = []
    filter_errors: list[float] = []
    pings = 0

    for step in range(steps):
        t = spec.phase + (step / max(steps - 1, 1)) * spec.speed
        if spec.loop:
            t = t % 1.0
        else:
            t = t % 2.0
            if t > 1.0:
                t = 2.0 - t

        true = point_on_path(spec.path, t)
        obs, sigma = noisy_ping(rng, city, true, base_noise, step)

        if step > 0:
            kx.predict(1.0)
            ky.predict(1.0)
        if obs is not None:
            pings += 1
            measurement_var = sigma * sigma
            kx.update(obs.x, measurement_var)
            ky.update(obs.y, measurement_var)
            noisy_errors.append(dist(obs, true))

        estimate = Pt(kx.pos, ky.pos)
        truth.append(true)
        observations.append(obs)
        estimates.append(estimate)
        filter_errors.append(dist(estimate, true))

    fx = kx.copy()
    fy = ky.copy()
    forecast: list[Pt] = []
    forecast_radius: list[float] = []
    for _ in range(18):
        fx.predict(1.0)
        fy.predict(1.0)
        forecast.append(Pt(fx.pos, fy.pos))
        forecast_radius.append(math.sqrt(max(1.0, fx.p00 + fy.p00)))

    noisy_rmse = math.sqrt(sum(e * e for e in noisy_errors) / max(len(noisy_errors), 1))
    filter_rmse = math.sqrt(sum(e * e for e in filter_errors) / max(len(filter_errors), 1))
    return Run(
        spec,
        truth,
        observations,
        estimates,
        forecast,
        forecast_radius,
        noisy_rmse,
        filter_rmse,
        pings,
    )


def poly(points: list[Pt]) -> str:
    return " ".join(f"{p.x:.1f},{p.y:.1f}" for p in points)


def path_d(points: list[Pt]) -> str:
    if not points:
        return ""
    return "M " + " L ".join(f"{p.x:.1f} {p.y:.1f}" for p in points)


def render_blocks(parts: list[str], city: City) -> None:
    for b in city.blocks:
        parts.append(
            f'<rect x="{b.x:.1f}" y="{b.y:.1f}" width="{b.w:.1f}" height="{b.h:.1f}" '
            f'rx="8" fill="{b.fill}" opacity="0.92"/>'
        )
        if b.kind == "park":
            for i in range(4):
                x = b.x + b.w * (0.18 + 0.18 * i)
                y = b.y + b.h * (0.32 + 0.12 * ((i * 7) % 3))
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#44d07b" opacity="0.35"/>'
                )
        elif b.kind == "water":
            parts.append(
                f'<path d="M {b.x + 10:.1f} {b.y + b.h * 0.55:.1f} C {b.x + b.w * 0.35:.1f} {b.y + b.h * 0.18:.1f}, '
                f'{b.x + b.w * 0.68:.1f} {b.y + b.h * 0.86:.1f}, {b.x + b.w - 10:.1f} {b.y + b.h * 0.42:.1f}" '
                'fill="none" stroke="#7dd3fc" stroke-width="3" opacity="0.35"/>'
            )
        elif b.kind == "canyon":
            bars = 2 + int(b.height * 5)
            for i in range(bars):
                x = b.x + 8 + i * (b.w - 16) / max(bars, 1)
                h = b.h * (0.22 + 0.45 * ((i * 3) % 5) / 4)
                parts.append(
                    f'<rect x="{x:.1f}" y="{b.y + b.h - h - 6:.1f}" width="4" height="{h:.1f}" '
                    'fill="#9ca3af" opacity="0.18"/>'
                )


def render_roads(parts: list[str], city: City) -> None:
    top = city.ys[0]
    bottom = city.ys[-1]
    left = city.xs[0]
    right = city.xs[-1]
    for i, x in enumerate(city.xs):
        width = 8 if i in (2, 5) else 5
        color = "#3b506c" if i in (2, 5) else "#27364c"
        parts.append(
            f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" y2="{bottom:.1f}" '
            f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'
        )
    for i, y in enumerate(city.ys):
        width = 8 if i in (2, 4) else 5
        color = "#3b506c" if i in (2, 4) else "#27364c"
        parts.append(
            f'<line x1="{left:.1f}" y1="{y:.1f}" x2="{right:.1f}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'
        )
    for x in city.xs:
        for y in city.ys:
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.1" fill="#94a3b8" opacity="0.28"/>'
            )


def render(seed: str, city: City, runs: list[Run], noise: float, steps: int) -> str:
    size = city.size
    avg_noisy = sum(r.noisy_rmse for r in runs) / len(runs)
    avg_filter = sum(r.filter_rmse for r in runs) / len(runs)
    gain = avg_noisy / max(avg_filter, 1e-9)
    pings = sum(r.pings for r in runs)
    expected = steps * len(runs)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">',
        "<defs>",
        '<radialGradient id="canyonGlow"><stop offset="0%" stop-color="#a78bfa" stop-opacity="0.22"/><stop offset="100%" stop-color="#a78bfa" stop-opacity="0"/></radialGradient>',
        '<filter id="soft"><feGaussianBlur stdDeviation="4"/></filter>',
        "</defs>",
        '<rect width="100%" height="100%" fill="#071018"/>',
        f'<text x="{size * 0.08:.1f}" y="38" fill="#e5f0ff" font-family="monospace" font-size="23" font-weight="700">kalmanville</text>',
        f'<text x="{size * 0.08:.1f}" y="62" fill="#8aa4c2" font-family="monospace" font-size="12">seed={esc(seed)}  steps={steps}  base_noise={noise:.1f}px  pings={pings}/{expected}</text>',
        f'<text x="{size * 0.08:.1f}" y="84" fill="#9fb9d8" font-family="monospace" font-size="12">noisy rmse {avg_noisy:.1f}px -> filter rmse {avg_filter:.1f}px  ({gain:.1f}x cleaner)</text>',
        f'<ellipse cx="{city.center.x:.1f}" cy="{city.center.y:.1f}" rx="{size * 0.23:.1f}" ry="{size * 0.18:.1f}" fill="url(#canyonGlow)"/>',
    ]

    render_blocks(parts, city)
    render_roads(parts, city)

    # Forecast heat belongs under the tracks: this is the toy's tiny world model.
    for run in runs:
        for i, (p, radius) in enumerate(zip(run.forecast, run.forecast_radius, strict=False)):
            alpha = max(0.015, 0.12 - i * 0.004)
            r = clamp(7 + radius * 0.18 + i * 0.75, 8, 48)
            parts.append(
                f'<circle cx="{p.x:.1f}" cy="{p.y:.1f}" r="{r:.1f}" fill="{run.spec.color}" '
                f'opacity="{alpha:.3f}" filter="url(#soft)"/>'
            )

    for run in runs:
        route = run.spec
        parts.append(
            f'<polyline points="{poly(route.path)}" fill="none" stroke="{route.color}" stroke-width="6" '
            'stroke-linecap="round" stroke-linejoin="round" opacity="0.18"/>'
        )
        parts.append(
            f'<path d="{path_d(run.truth)}" fill="none" stroke="{route.color}" stroke-width="1.2" '
            'stroke-dasharray="5 6" opacity="0.45"/>'
        )
        obs_points = [p for i, p in enumerate(run.observations) if p is not None and i % 2 == 0]
        for p in obs_points:
            parts.append(
                f'<circle cx="{p.x:.1f}" cy="{p.y:.1f}" r="2.6" fill="#ff9f66" opacity="0.48"/>'
            )
        parts.append(
            f'<path d="{path_d(run.estimates)}" fill="none" stroke="{route.color}" stroke-width="3.2" '
            'stroke-linecap="round" stroke-linejoin="round" opacity="0.92"/>'
        )
        parts.append(
            f'<path d="{path_d(run.forecast)}" fill="none" stroke="{route.color}" stroke-width="2.2" '
            'stroke-linecap="round" stroke-dasharray="3 6" opacity="0.72"/>'
        )
        final = run.estimates[-1]
        parts.append(
            f'<circle cx="{final.x:.1f}" cy="{final.y:.1f}" r="8.5" fill="#071018" stroke="{route.color}" '
            'stroke-width="3"/>'
        )
        parts.append(f'<circle cx="{final.x:.1f}" cy="{final.y:.1f}" r="3" fill="{route.color}"/>')

    legend_x = size * 0.66
    legend_y = 30
    parts.append(
        f'<rect x="{legend_x - 14:.1f}" y="{legend_y - 16:.1f}" width="{size * 0.27:.1f}" height="92" rx="12" '
        'fill="#0d1824" stroke="#203247" opacity="0.94"/>'
    )
    parts.append(
        f'<text x="{legend_x:.1f}" y="{legend_y:.1f}" fill="#dbeafe" font-family="monospace" font-size="11" font-weight="700">legend</text>'
    )
    legend_items = [
        ("truth route", "#94a3b8", "dashed"),
        ("noisy sensor ping", "#ff9f66", "dots"),
        ("filtered estimate", "#5eead4", "line"),
        ("forecast heat", "#facc15", "glow"),
    ]
    for i, (label, color, kind) in enumerate(legend_items):
        y = legend_y + 18 + i * 15
        if kind == "dots":
            parts.append(
                f'<circle cx="{legend_x + 5:.1f}" cy="{y - 3:.1f}" r="3" fill="{color}" opacity="0.7"/>'
            )
        else:
            dash = ' stroke-dasharray="4 4"' if kind == "dashed" else ""
            width = 7 if kind == "glow" else 3
            opacity = 0.24 if kind == "glow" else 0.85
            parts.append(
                f'<line x1="{legend_x:.1f}" y1="{y - 3:.1f}" x2="{legend_x + 22:.1f}" y2="{y - 3:.1f}" '
                f'stroke="{color}" stroke-width="{width}" opacity="{opacity}"{dash}/>'
            )
        parts.append(
            f'<text x="{legend_x + 34:.1f}" y="{y:.1f}" fill="#9fb9d8" font-family="monospace" font-size="10">{label}</text>'
        )

    row_y = size * 0.935
    parts.append(
        f'<rect x="{size * 0.08:.1f}" y="{row_y - 25:.1f}" width="{size * 0.84:.1f}" height="44" rx="12" '
        'fill="#0d1824" stroke="#203247" opacity="0.96"/>'
    )
    for i, run in enumerate(runs):
        x = size * 0.10 + i * size * 0.205
        parts.append(f'<circle cx="{x:.1f}" cy="{row_y - 8:.1f}" r="5" fill="{run.spec.color}"/>')
        parts.append(
            f'<text x="{x + 10:.1f}" y="{row_y - 4:.1f}" fill="#dbeafe" font-family="monospace" font-size="10">{run.spec.name}</text>'
        )
        parts.append(
            f'<text x="{x + 10:.1f}" y="{row_y + 10:.1f}" fill="#8aa4c2" font-family="monospace" font-size="9">gps {run.noisy_rmse:.0f}px / filter {run.filter_rmse:.0f}px</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def build(seed: str, size: int, steps: int, noise: float) -> str:
    city = make_city(seed, size)
    routes = make_routes(city, seed)
    runs = [simulate_route(city, route, seed, steps, noise) for route in routes]
    return render(seed, city, runs, noise, steps)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a noisy transit Kalman-filter map as SVG.")
    parser.add_argument("--seed", default="morning", help="deterministic city seed")
    parser.add_argument("--size", type=int, default=900, help="SVG width/height in pixels")
    parser.add_argument("--steps", type=int, default=96, help="sensor updates to simulate")
    parser.add_argument("--noise", type=float, default=20.0, help="base GPS noise in pixels")
    parser.add_argument("--out", default="scratch/kalmanville.svg", help="output SVG path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.size < 520:
        raise SystemExit("--size must be at least 520")
    if args.steps < 8:
        raise SystemExit("--steps must be at least 8")
    if args.noise <= 0:
        raise SystemExit("--noise must be positive")

    svg = build(args.seed, args.size, args.steps, args.noise)
    out = Path(args.out)
    if out.parent:
        os.makedirs(out.parent, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
