"""drift_panorama.py — generate a cross-section panorama of the Drift.

The Drift is an alien world of landmasses suspended in a luminous atmospheric
sea. This generator emits a single SVG showing all 8 biomes stacked vertically,
with creatures and atmospheric effects rendered in procedural detail.

Output: toys/svgart/examples/drift_panorama.svg
"""

from __future__ import annotations

import math
import random
from pathlib import Path

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

WIDTH = 1600
HEIGHT = 3200
SEED = 42

rng = random.Random(SEED)

# biome vertical boundaries (y-coordinates)
BIOME_BOUNDS = {
    "Rime": (0, 400),
    "Aether": (400, 800),
    "Canopy": (800, 1200),
    "Underglow": (1200, 1600),
    "Mire": (1600, 2000),
    "Bone Fields": (2000, 2400),
    "Glass Wastes": (2400, 2800),
    "the Vent": (2800, 3200),
}

OUTPUT = Path(__file__).parent / "examples" / "drift_panorama.svg"

# ---------------------------------------------------------------------------
# svg element builders
# ---------------------------------------------------------------------------


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def el(tag: str, attrs: dict | None = None, children: list | None = None, self_closing: bool = False) -> str:
    attrs = attrs or {}
    # convert underscores to hyphens (stroke_width -> stroke-width)
    clean_attrs = {k.replace("_", "-"): v for k, v in attrs.items()}
    a = " ".join(f'{k}="{v}"' for k, v in clean_attrs.items())
    if self_closing:
        return f"<{tag} {a} />"
    inner = "".join(children or [])
    return f"<{tag} {a}>{inner}</{tag}>"


def path(d: str, **attrs) -> str:
    return el("path", {"d": d, **attrs})


def circle(cx: float, cy: float, r: float, **attrs) -> str:
    return el("circle", {"cx": cx, "cy": cy, "r": r, **attrs}, self_closing=True)


def ellipse(cx: float, cy: float, rx: float, ry: float, **attrs) -> str:
    return el("ellipse", {"cx": cx, "cy": cy, "rx": rx, "ry": ry, **attrs}, self_closing=True)


def rect(x: float, y: float, w: float, h: float, **attrs) -> str:
    return el("rect", {"x": x, "y": y, "width": w, "height": h, **attrs}, self_closing=True)


def line(x1: float, y1: float, x2: float, y2: float, **attrs) -> str:
    return el("line", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, **attrs}, self_closing=True)


def polygon(points: list, **attrs) -> str:
    pts = " ".join(f"{x},{y}" for x, y in points)
    return el("polygon", {"points": pts, **attrs}, self_closing=True)


def polyline(points: list, **attrs) -> str:
    pts = " ".join(f"{x},{y}" for x, y in points)
    return el("polyline", {"points": pts, **attrs}, self_closing=True)


def group(contents: list, **attrs) -> str:
    return el("g", {**attrs}, contents)


def text_el(x: float, y: float, content: str, **attrs) -> str:
    return el("text", {"x": x, "y": y, **attrs}, [esc(content)])


# ---------------------------------------------------------------------------
# gradient and filter definitions
# ---------------------------------------------------------------------------


def defs_section() -> str:
    defs = []

    # --- sky gradients per biome ---

    # Rime: deep dark to frosty
    defs.append(
        el("linearGradient", {"id": "grad-rime", "x1": 0, "y1": 0, "x2": 0, "y2": 1}, [
            el("stop", {"offset": "0%", "stop-color":"#0a0a1a", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "60%", "stop-color":"#101830", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#1a2040", "stop-opacity":1}, self_closing=True),
        ])
    )

    # Aether: thin luminous atmosphere
    defs.append(
        el("linearGradient", {"id": "grad-aether", "x1": 0, "y1": 0, "x2": 0, "y2": 1}, [
            el("stop", {"offset": "0%", "stop-color":"#1a2040", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "50%", "stop-color":"#2a1848", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#1a2818", "stop-opacity":1}, self_closing=True),
        ])
    )

    # Canopy: warm sunlight
    defs.append(
        el("linearGradient", {"id": "grad-canopy", "x1": 0, "y1": 0, "x2": 0, "y2": 1}, [
            el("stop", {"offset": "0%", "stop-color":"#1a2818", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "30%", "stop-color":"#2a3818", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#15200a", "stop-opacity":1}, self_closing=True),
        ])
    )

    # Underglow: bioluminescent dark
    defs.append(
        el("linearGradient", {"id": "grad-underglow", "x1": 0, "y1": 0, "x2": 0, "y2": 1}, [
            el("stop", {"offset": "0%", "stop-color":"#15200a", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "50%", "stop-color":"#0a0815", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#080612", "stop-opacity":1}, self_closing=True),
        ])
    )

    # Mire: murky swamp
    defs.append(
        el("linearGradient", {"id": "grad-mire", "x1": 0, "y1": 0, "x2": 0, "y2": 1}, [
            el("stop", {"offset": "0%", "stop-color":"#080612", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "50%", "stop-color":"#0e0a0a", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#1a1208", "stop-opacity":1}, self_closing=True),
        ])
    )

    # Bone Fields: pale desolate
    defs.append(
        el("linearGradient", {"id": "grad-bone", "x1": 0, "y1": 0, "x2": 0, "y2": 1}, [
            el("stop", {"offset": "0%", "stop-color":"#1a1208", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "50%", "stop-color":"#2a2018", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#382818", "stop-opacity":1}, self_closing=True),
        ])
    )

    # Glass Wastes: refractive heat
    defs.append(
        el("linearGradient", {"id": "grad-glass", "x1": 0, "y1": 0, "x2": 0, "y2": 1}, [
            el("stop", {"offset": "0%", "stop-color":"#382818", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "50%", "stop-color":"#3a3010", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#2a1808", "stop-opacity":1}, self_closing=True),
        ])
    )

    # the Vent: dark deep with thermal glow
    defs.append(
        el("linearGradient", {"id": "grad-vent", "x1": 0, "y1": 0, "x2": 0, "y2": 1}, [
            el("stop", {"offset": "0%", "stop-color":"#2a1808", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "40%", "stop-color":"#1a0805", "stop-opacity":1}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#080205", "stop-opacity":1}, self_closing=True),
        ])
    )

    # --- radial gradients for glow effects ---

    for color, gid in [
        ("#4a8aff", "glow-blue"),
        ("#a040ff", "glow-purple"),
        ("#ff6020", "glow-orange"),
        ("#20ffa0", "glow-green"),
        ("#ff4060", "glow-red"),
        ("#ffff80", "glow-yellow"),
        ("#60d0ff", "glow-cyan"),
        ("#ff80c0", "glow-pink"),
        ("#c0a0ff", "glow-lavender"),
        ("#80ff40", "glow-lime"),
    ]:
        defs.append(
            el("radialGradient", {"id": gid, "cx": "50%", "cy": "50%", "r": "50%"}, [
                el("stop", {"offset": "0%", "stop-color":color, "stop-opacity":0.8}, self_closing=True),
                el("stop", {"offset": "60%", "stop-color":color, "stop-opacity":0.2}, self_closing=True),
                el("stop", {"offset": "100%", "stop-color":color, "stop-opacity":0}, self_closing=True),
            ])
        )

    # aurora gradient
    defs.append(
        el("linearGradient", {"id": "aurora1", "x1": 0, "y1": 0, "x2": 1, "y2": 0}, [
            el("stop", {"offset": "0%", "stop-color":"#00ff80", "stop-opacity":0}, self_closing=True),
            el("stop", {"offset": "30%", "stop-color":"#20ffa0", "stop-opacity":0.4}, self_closing=True),
            el("stop", {"offset": "60%", "stop-color":"#60d0ff", "stop-opacity":0.3}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#a040ff", "stop-opacity":0}, self_closing=True),
        ])
    )

    defs.append(
        el("linearGradient", {"id": "aurora2", "x1": 0, "y1": 0, "x2": 1, "y2": 0}, [
            el("stop", {"offset": "0%", "stop-color":"#ff4060", "stop-opacity":0}, self_closing=True),
            el("stop", {"offset": "40%", "stop-color":"#ff80c0", "stop-opacity":0.25}, self_closing=True),
            el("stop", {"offset": "70%", "stop-color":"#c0a0ff", "stop-opacity":0.2}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#60d0ff", "stop-opacity":0}, self_closing=True),
        ])
    )

    # thermal vent glow
    defs.append(
        el("radialGradient", {"id": "thermal-glow", "cx": "50%", "cy": "50%", "r": "50%"}, [
            el("stop", {"offset": "0%", "stop-color":"#ff6020", "stop-opacity":0.9}, self_closing=True),
            el("stop", {"offset": "30%", "stop-color":"#ff4010", "stop-opacity":0.5}, self_closing=True),
            el("stop", {"offset": "70%", "stop-color":"#801005", "stop-opacity":0.2}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#200000", "stop-opacity":0}, self_closing=True),
        ])
    )

    # bioluminescent glow
    defs.append(
        el("radialGradient", {"id": "biolum-glow", "cx": "50%", "cy": "50%", "r": "50%"}, [
            el("stop", {"offset": "0%", "stop-color":"#80ff40", "stop-opacity":0.7}, self_closing=True),
            el("stop", {"offset": "50%", "stop-color":"#40a020", "stop-opacity":0.2}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#204010", "stop-opacity":0}, self_closing=True),
        ])
    )

    # sun glow for glass wastes
    defs.append(
        el("radialGradient", {"id": "sun-glow", "cx": "50%", "cy": "30%", "r": "60%"}, [
            el("stop", {"offset": "0%", "stop-color":"#ffffd0", "stop-opacity":0.8}, self_closing=True),
            el("stop", {"offset": "30%", "stop-color":"#ffa040", "stop-opacity":0.3}, self_closing=True),
            el("stop", {"offset": "100%", "stop-color":"#ff4010", "stop-opacity":0}, self_closing=True),
        ])
    )

    # --- filters ---

    # soft glow blur
    defs.append(
        el("filter", {"id": "glow-soft", "x": "-50%", "y": "-50%", "width": "200%", "height": "200%"}, [
            el("feGaussianBlur", {"stdDeviation": 4, "result": "blur"}, self_closing=True),
            el("feMerge", {}, [
                el("feMergeNode", {"in": "blur"}, self_closing=True),
                el("feMergeNode", {"in": "SourceGraphic"}, self_closing=True),
            ]),
        ])
    )

    # strong glow
    defs.append(
        el("filter", {"id": "glow-strong", "x": "-50%", "y": "-50%", "width": "200%", "height": "200%"}, [
            el("feGaussianBlur", {"stdDeviation": 8, "result": "blur"}, self_closing=True),
            el("feMerge", {}, [
                el("feMergeNode", {"in": "blur"}, self_closing=True),
                el("feMergeNode", {"in": "blur"}, self_closing=True),
                el("feMergeNode", {"in": "SourceGraphic"}, self_closing=True),
            ]),
        ])
    )

    # misty blur
    defs.append(
        el("filter", {"id": "mist", "x": "-50%", "y": "-50%", "width": "200%", "height": "200%"}, [
            el("feGaussianBlur", {"stdDeviation": 12}, self_closing=True),
        ])
    )

    # light blur
    defs.append(
        el("filter", {"id": "blur-light", "x": "-50%", "y": "-50%", "width": "200%", "height": "200%"}, [
            el("feGaussianBlur", {"stdDeviation": 2}, self_closing=True),
        ])
    )

    # heavy blur for atmospheric depth
    defs.append(
        el("filter", {"id": "blur-heavy", "x": "-50%", "y": "-50%", "width": "200%", "height": "200%"}, [
            el("feGaussianBlur", {"stdDeviation": 20}, self_closing=True),
        ])
    )

    # crystal refraction effect
    defs.append(
        el("filter", {"id": "crystal", "x": "-20%", "y": "-20%", "width": "140%", "height": "140%"}, [
            el("feGaussianBlur", {"stdDeviation": 1, "result": "blur"}, self_closing=True),
            el("feSpecularLighting", {
                "in": "blur", "result": "spec",
                "surfaceScale": 3,
                "specularConstant": 1.5,
                "specularExponent": 20,
                "lighting-color":"#a0d0ff",
            }, [
                el("fePointLight", {"x": 100, "y": 50, "z": 200}, self_closing=True),
            ]),
            el("feComposite", {"in": "spec", "in2": "SourceGraphic", "operator": "in", "result": "specOut"}, self_closing=True),
            el("feMerge", {}, [
                el("feMergeNode", {"in": "SourceGraphic"}, self_closing=True),
                el("feMergeNode", {"in": "specOut"}, self_closing=True),
            ]),
        ])
    )

    # --- patterns ---

    # crystal pattern for Rime
    defs.append(
        el("pattern", {"id": "crystal-tex", "width": 40, "height": 40, "patternUnits": "userSpaceOnUse"}, [
            path("M0,0 L20,10 L40,0 M20,10 L20,30 M0,40 L20,30 L40,40",
                 stroke="#3060a0", stroke_width=0.5, fill="none", opacity=0.3),
        ])
    )

    # bark pattern
    defs.append(
        el("pattern", {"id": "bark-tex", "width": 20, "height": 60, "patternUnits": "userSpaceOnUse"}, [
            path("M5,0 Q8,15 5,30 Q2,45 5,60", stroke="#3a2810", stroke_width=1.5, fill="none", opacity=0.6),
            path("M12,0 Q15,20 12,40 Q9,50 12,60", stroke="#4a3018", stroke_width=1, fill="none", opacity=0.4),
            path("M17,5 Q19,25 17,45", stroke="#2a1808", stroke_width=0.8, fill="none", opacity=0.5),
        ])
    )

    # fungal dot pattern for Underglow
    defs.append(
        el("pattern", {"id": "fungal-tex", "width": 30, "height": 30, "patternUnits": "userSpaceOnUse"}, [
            circle(10, 10, 2, fill="#80ff40", opacity=0.15),
            circle(20, 22, 1.5, fill="#40ffa0", opacity=0.1),
            circle(5, 25, 1, fill="#80ff40", opacity=0.2),
        ])
    )

    return el("defs", {}, defs)


# ---------------------------------------------------------------------------
# biome renderers
# ---------------------------------------------------------------------------


def render_rime() -> str:
    """Rime: frozen upper atmosphere, crystalline ice, aurora."""
    y0, y1 = BIOME_BOUNDS["Rime"]
    elements = []

    # background
    elements.append(rect(0, y0, WIDTH, y1 - y0, fill="url(#grad-rime)"))

    # aurora ribbons
    for i in range(3):
        y_aurora = y0 + 50 + i * 80
        aurora_id = "aurora1" if i % 2 == 0 else "aurora2"
        # wavy ribbon
        pts = []
        for x in range(0, WIDTH + 20, 20):
            y = y_aurora + math.sin(x * 0.005 + i * 1.5) * 30 + rng.gauss(0, 5)
            pts.append((x, y))
        d = f"M{pts[0][0]},{pts[0][1]} "
        for px, py in pts[1:]:
            d += f"L{px},{py} "
        d += f"L{WIDTH},{y_aurora + 40} "
        for px, py in reversed(pts[1:]):
            d += f"L{px},{py + 40} "
        d += "Z"
        elements.append(path(d, fill=f"url(#{aurora_id})", opacity=0.5, filter="url(#blur-heavy)"))

    # stars
    for _ in range(60):
        sx = rng.uniform(0, WIDTH)
        sy = rng.uniform(y0, y0 + 200)
        sr = rng.uniform(0.5, 2)
        elements.append(circle(sx, sy, sr, fill="#ffffff", opacity=rng.uniform(0.3, 0.9)))

    # crystalline ice formations — hexagonal prisms
    for i in range(8):
        cx = rng.uniform(100, WIDTH - 100)
        cy = rng.uniform(y0 + 150, y1 - 50)
        h = rng.uniform(60, 180)
        w = rng.uniform(20, 40)

        # hexagonal ice column
        hex_pts = []
        for j in range(6):
            angle = j * math.pi / 3
            hx = cx + w * math.cos(angle)
            hy = cy + h * 0.3 * math.sin(angle)
            hex_pts.append((hx, hy))

        # main column body
        top_pts = [(cx + w * math.cos(j * math.pi / 3), cy - h * 0.2 + w * 0.3 * math.sin(j * math.pi / 3)) for j in range(6)]
        bot_pts = [(cx + w * math.cos(j * math.pi / 3), cy + h + w * 0.3 * math.sin(j * math.pi / 3)) for j in range(6)]

        # column body — use gradient
        col_d = f"M{top_pts[0][0]},{top_pts[0][1]} "
        for px, py in top_pts[1:]:
            col_d += f"L{px},{py} "
        col_d += f"L{bot_pts[5][0]},{bot_pts[5][1]} "
        for px, py in reversed(bot_pts[:5]):
            col_d += f"L{px},{py} "
        col_d += "Z"
        elements.append(path(col_d, fill="#103040", stroke="#3060a0", stroke_width=1, opacity=0.7))

        # top hexagon face
        hex_top = " ".join(f"{px},{py}" for px, py in top_pts)
        elements.append(polygon(top_pts, fill="#2050a0", opacity=0.4, stroke="#60a0d0", stroke_width=0.5))

        # internal facets — light catching edges
        for j in range(3):
            elements.append(line(top_pts[j][0], top_pts[j][1], bot_pts[j][0], bot_pts[j][1],
                                 stroke="#80c0e0", stroke_width=0.5, opacity=0.3))

        # glow at base
        elements.append(circle(cx, cy + h, w * 2, fill="url(#glow-cyan)", opacity=0.3, filter="url(#glow-soft)"))

    # ice particles — floating crystals
    for _ in range(40):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(y0 + 100, y1 - 20)
        ps = rng.uniform(2, 6)
        # small diamond crystal
        elements.append(polygon([(px, py - ps), (px + ps * 0.5, py), (px, py + ps), (px - ps * 0.5, py)],
                                fill="#a0d0ff", opacity=rng.uniform(0.3, 0.7), stroke="#60a0c0", stroke_width=0.3))

    # label
    elements.append(text_el(30, y0 + 30, "RIME", fill="#80a0c0", font_size=14, font_family="serif",
                            letter_spacing=4, opacity=0.5))

    return group(elements, id="biome-rime")


def render_aether() -> str:
    """Aether: open sky, floating gas-bladder creatures, electrostatic ribbons."""
    y0, y1 = BIOME_BOUNDS["Aether"]
    elements = []

    elements.append(rect(0, y0, WIDTH, y1 - y0, fill="url(#grad-aether)"))

    # atmospheric haze layers
    for i in range(5):
        elements.append(rect(0, y0 + i * 80, WIDTH, 40, fill="#3a2050", opacity=0.05, filter="url(#blur-heavy)"))

    # floating gas-bladder creatures (Aerochorda-style)
    for i in range(6):
        cx = rng.uniform(150, WIDTH - 150)
        cy = rng.uniform(y0 + 40, y1 - 40)
        scale = rng.uniform(0.6, 1.4)

        # chain of gas bladders
        n_bladders = rng.randint(3, 8)
        bladder_w = 25 * scale
        bladder_h = 35 * scale

        for j in range(n_bladders):
            bx = cx + math.sin(j * 0.5) * 15 * scale
            by = cy + j * bladder_h * 0.7

            # bladder body
            elements.append(ellipse(bx, by, bladder_w, bladder_h * 0.6,
                                    fill="#60d0ff", opacity=0.3, stroke="#80e0ff", stroke_width=0.5))
            # highlight
            elements.append(ellipse(bx - bladder_w * 0.3, by - bladder_h * 0.2, bladder_w * 0.2, bladder_h * 0.15,
                                    fill="#ffffff", opacity=0.2))
            # connecting filament
            if j < n_bladders - 1:
                elements.append(line(bx, by + bladder_h * 0.6,
                                     bx + math.sin((j + 1) * 0.5) * 15 * scale,
                                     by + bladder_h * 0.7 + bladder_h * 0.6,
                                     stroke="#4080a0", stroke_width=0.8, opacity=0.4))

        # trailing mucus net / electrostatic threads
        net_y = cy + n_bladders * bladder_h * 0.7
        for k in range(8):
            nx = cx + rng.uniform(-60, 60) * scale
            ny = net_y + rng.uniform(10, 80) * scale
            elements.append(line(cx, net_y, nx, ny, stroke="#80e0ff", stroke_width=0.3, opacity=0.15))
            elements.append(circle(nx, ny, 1, fill="#a0d0ff", opacity=0.2))

    # electrostatic ribbon creature (Lissajous pilot style)
    for i in range(3):
        cx = rng.uniform(200, WIDTH - 200)
        cy = rng.uniform(y0 + 50, y1 - 50)
        # triangular aerogel body
        s = rng.uniform(30, 50)
        tri_pts = [(cx, cy - s), (cx + s, cy + s * 0.5), (cx - s, cy + s * 0.5)]
        elements.append(polygon(tri_pts, fill="#c0a0ff", opacity=0.2, stroke="#e0c0ff", stroke_width=0.5))
        # piezo filaments
        for k in range(3):
            fx = cx + (k - 1) * s * 0.4
            elements.append(line(fx, cy - s, fx, cy - s * 2, stroke="#e0c0ff", stroke_width=0.3, opacity=0.3))
        # glow
        elements.append(circle(cx, cy, s * 2, fill="url(#glow-lavender)", opacity=0.2, filter="url(#glow-soft)"))

    # aeroplankton — tiny floating dots
    for _ in range(200):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(y0, y1)
        ps = rng.uniform(0.5, 2)
        elements.append(circle(px, py, ps, fill="#a0d0ff", opacity=rng.uniform(0.1, 0.4)))

    # lightning flicker (distant atmospheric discharge)
    for i in range(2):
        lx = rng.uniform(200, WIDTH - 200)
        ly = y0 + rng.uniform(50, 200)
        # jagged lightning path
        ld = f"M{lx},{ly} "
        cy_l = ly
        for j in range(6):
            lx += rng.uniform(-30, 30)
            cy_l += rng.uniform(20, 50)
            ld += f"L{lx},{cy_l} "
        elements.append(path(ld, stroke="#ffffff", stroke_width=0.8, opacity=0.3, fill="none", filter="url(#glow-soft)"))

    elements.append(text_el(30, y0 + 30, "AETHER", fill="#a080c0", font_size=14, font_family="serif",
                            letter_spacing=4, opacity=0.5))

    return group(elements, id="biome-aether")


def render_canopy() -> str:
    """Canopy: world-trees, sunlit surface, bark detail."""
    y0, y1 = BIOME_BOUNDS["Canopy"]
    elements = []

    elements.append(rect(0, y0, WIDTH, y1 - y0, fill="url(#grad-canopy)"))

    # dappled sunlight
    for _ in range(15):
        sx = rng.uniform(0, WIDTH)
        sy = rng.uniform(y0, y0 + 200)
        sr = rng.uniform(40, 100)
        elements.append(circle(sx, sy, sr, fill="#ffd060", opacity=0.04, filter="url(#blur-heavy)"))

    # world-tree trunks — massive columns
    for i in range(4):
        tx = 100 + i * 420 + rng.uniform(-30, 30)
        tw = rng.uniform(80, 120)

        # trunk body with bark texture
        trunk_d = f"M{tx - tw / 2},{y1} "
        trunk_d += f"Q{tx - tw / 2 - 5},{y0 + 100} {tx - tw / 2 + 10},{y0} "
        trunk_d += f"L{tx + tw / 2 - 10},{y0} "
        trunk_d += f"Q{tx + tw / 2 + 5},{y0 + 100} {tx + tw / 2},{y1} "
        trunk_d += "Z"
        elements.append(path(trunk_d, fill="#2a1a08", stroke="#1a0a04", stroke_width=1))

        # bark texture overlay
        elements.append(path(trunk_d, fill="url(#bark-tex)", opacity=0.8))

        # bark grooves
        for g in range(8):
            gx = tx - tw / 2 + (g / 7) * tw
            elements.append(path(
                f"M{gx},{y0} Q{gx + 3},{y0 + 100} {gx},{y1}",
                stroke="#1a0a04", stroke_width=1.5, fill="none", opacity=0.5
            ))

        # moss/lichen on trunk
        for m in range(10):
            mx = tx - tw / 2 + rng.uniform(0, tw)
            my = y0 + rng.uniform(0, y1 - y0)
            mr = rng.uniform(3, 8)
            elements.append(circle(mx, my, mr, fill="#3a5020", opacity=0.3))

        # branch going off to the side
        if i < 3:
            by = y0 + rng.uniform(50, 200)
            bd = f"M{tx + tw / 2},{by} Q{tx + tw + 30},{by - 10} {tx + tw + 60},{by + 20}"
            elements.append(path(bd, stroke="#2a1a08", stroke_width=8, fill="none", stroke_linecap="round"))
            # leaves on branch
            for l in range(15):
                lx = tx + tw + 40 + rng.uniform(-20, 30)
                ly = by + 10 + rng.uniform(-15, 25)
                elements.append(ellipse(lx, ly, 4, 2, fill="#4a6020", opacity=0.6, transform=f"rotate({rng.uniform(-30, 30)} {lx} {ly})"))

    # canopy surface — leafy top
    for i in range(80):
        lx = rng.uniform(0, WIDTH)
        ly = y0 + rng.uniform(-20, 60)
        lr = rng.uniform(8, 20)
        col = rng.choice(["#3a5018", "#4a6020", "#2a4010", "#5a7028"])
        elements.append(ellipse(lx, ly, lr, lr * 0.5, fill=col, opacity=rng.uniform(0.4, 0.7)))

    # Crownforge creature — stilt walker with mirror carapace
    cx, cy = WIDTH * 0.25, y0 + 250
    # legs
    for leg in range(6):
        lx = cx + (leg - 2.5) * 15
        elements.append(line(lx, cy, lx + (leg - 2.5) * 5, cy + 80,
                              stroke="#4a3018", stroke_width=2, stroke_linecap="round"))
    # parabolic mirror body
    body_pts = []
    for a in range(-80, 81, 10):
        bx = cx + a * 0.5
        by = cy - 20 + (a * a) * 0.003
        body_pts.append((bx, by))
    body_d = f"M{body_pts[0][0]},{body_pts[0][1]} "
    for px, py in body_pts[1:]:
        body_d += f"L{px},{py} "
    body_d += f"L{cx + 40},{cy} L{cx - 40},{cy} Z"
    elements.append(path(body_d, fill="#80a0c0", opacity=0.4, stroke="#c0e0ff", stroke_width=0.5))
    # focused light beam
    elements.append(path(f"M{cx},{cy - 20} L{cx - 30},{cy + 120} L{cx + 30},{cy + 120} Z",
                         fill="#ffff80", opacity=0.1, filter="url(#glow-soft)"))

    # Pilothusk — rolling gall-ball creature
    px2 = WIDTH * 0.6
    py2 = y0 + 300
    elements.append(circle(px2, py2, 12, fill="#5a4020", opacity=0.7, stroke="#3a2010", stroke_width=1))
    elements.append(circle(px2 - 4, py2 - 4, 5, fill="#6a5028", opacity=0.5))

    elements.append(text_el(30, y0 + 30, "CANOPY", fill="#608040", font_size=14, font_family="serif",
                            letter_spacing=4, opacity=0.5))

    return group(elements, id="biome-canopy")


def render_underglow() -> str:
    """Underglow: bioluminescent fungal forests, glowing networks."""
    y0, y1 = BIOME_BOUNDS["Underglow"]
    elements = []

    elements.append(rect(0, y0, WIDTH, y1 - y0, fill="url(#grad-underglow)"))

    # background fungal texture
    elements.append(rect(0, y0, WIDTH, y1 - y0, fill="url(#fungal-tex)", opacity=0.5))

    # bioluminescent glow patches
    for _ in range(12):
        gx = rng.uniform(0, WIDTH)
        gy = rng.uniform(y0, y1)
        gr = rng.uniform(60, 150)
        glow_col = rng.choice(["url(#biolum-glow)", "url(#glow-green)", "url(#glow-cyan)"])
        elements.append(circle(gx, gy, gr, fill=glow_col, opacity=0.2, filter="url(#blur-heavy)"))

    # fungal columns — mushroom-like structures
    for i in range(12):
        cx = rng.uniform(50, WIDTH - 50)
        cy_base = y1 - rng.uniform(20, 80)
        ch = rng.uniform(60, 150)
        cw = rng.uniform(15, 30)

        # stalk
        stalk_d = f"M{cx - cw * 0.3},{cy_base} Q{cx - cw * 0.5},{cy_base - ch * 0.5} {cx - cw * 0.3},{cy_base - ch} "
        stalk_d += f"L{cx + cw * 0.3},{cy_base - ch} Q{cx + cw * 0.5},{cy_base - ch * 0.5} {cx + cw * 0.3},{cy_base} Z"
        elements.append(path(stalk_d, fill="#2a1a30", opacity=0.8))

        # cap
        cap_w = cw * 2.5
        cap_h = cw * 1.2
        cap_d = f"M{cx - cap_w},{cy_base - ch} Q{cx},{cy_base - ch - cap_h} {cx + cap_w},{cy_base - ch} Z"
        cap_color = rng.choice(["#4a2080", "#205060", "#602040", "#204030"])
        elements.append(path(cap_d, fill=cap_color, opacity=0.7))
        # glowing gills under cap
        elements.append(ellipse(cx, cy_base - ch + 2, cap_w * 0.8, cap_h * 0.3, fill="#80ff40", opacity=0.15, filter="url(#glow-soft)"))
        # bioluminescent spots on cap
        for _ in range(rng.randint(3, 8)):
            sx = cx + rng.uniform(-cap_w * 0.7, cap_w * 0.7)
            sy = cy_base - ch + rng.uniform(-cap_h * 0.3, 0)
            sr = rng.uniform(1, 3)
            sc = rng.choice(["#80ff40", "#40ffa0", "#60d0ff"])
            elements.append(circle(sx, sy, sr, fill=sc, opacity=0.6, filter="url(#glow-soft)"))

    # fungal network threads — hyphae connecting columns
    thread_points = [(rng.uniform(50, WIDTH - 50), y0 + rng.uniform(0, y1 - y0)) for _ in range(20)]
    for i in range(len(thread_points)):
        for j in range(i + 1, len(thread_points)):
            x1, y1_ = thread_points[i]
            x2, y2_ = thread_points[j]
            dist = math.hypot(x2 - x1, y2_ - y1_)
            if dist < 200 and rng.random() < 0.3:
                # curved hypha
                mx = (x1 + x2) / 2 + rng.uniform(-30, 30)
                my = (y1_ + y2_) / 2 + rng.uniform(-30, 30)
                elements.append(path(f"M{x1},{y1_} Q{mx},{my} {x2},{y2_}",
                                     stroke="#40a060", stroke_width=0.5, fill="none", opacity=0.2))
                # glowing node
                elements.append(circle(mx, my, 1.5, fill="#80ff40", opacity=0.4, filter="url(#glow-soft)"))

    # Wickfall — hanging lure creature
    for i in range(4):
        cx = rng.uniform(100, WIDTH - 100)
        cy_top = y0 + rng.uniform(10, 50)
        length = rng.uniform(100, 200)
        # hanging thread
        elements.append(line(cx, cy_top, cx, cy_top + length, stroke="#2a1a30", stroke_width=1, opacity=0.5))
        # glowing lure at bottom
        elements.append(circle(cx, cy_top + length, 5, fill="#80ff40", opacity=0.7, filter="url(#glow-strong)"))
        elements.append(circle(cx, cy_top + length, 15, fill="#80ff40", opacity=0.1, filter="url(#blur-heavy)"))

    # Mimolux — flat leaf-shaped predator with bioluminescent spoofing
    mx, my = WIDTH * 0.6, y0 + 250
    leaf_pts = [(mx - 30, my), (mx - 10, my - 20), (mx + 20, my - 15), (mx + 35, my), (mx + 20, my + 15), (mx - 10, my + 20)]
    elements.append(polygon(leaf_pts, fill="#1a0820", opacity=0.7, stroke="#40a060", stroke_width=0.5))
    # false flash spots
    for _ in range(5):
        fx = mx + rng.uniform(-20, 20)
        fy = my + rng.uniform(-15, 15)
        elements.append(circle(fx, fy, 2, fill="#80ff40", opacity=0.5, filter="url(#glow-soft)"))

    # spores — floating bioluminescent particles
    for _ in range(150):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(y0, y1)
        ps = rng.uniform(0.5, 2)
        col = rng.choice(["#80ff40", "#40ffa0", "#60d0ff"])
        elements.append(circle(px, py, ps, fill=col, opacity=rng.uniform(0.1, 0.5)))

    elements.append(text_el(30, y0 + 30, "UNDERGLOW", fill="#40a060", font_size=14, font_family="serif",
                            letter_spacing=4, opacity=0.5))

    return group(elements, id="biome-underglow")


def render_mire() -> str:
    """Mire: swampy decay, mist, organic textures."""
    y0, y1 = BIOME_BOUNDS["Mire"]
    elements = []

    elements.append(rect(0, y0, WIDTH, y1 - y0, fill="url(#grad-mire)"))

    # mist layers
    for i in range(6):
        my = y0 + i * 70 + rng.uniform(-20, 20)
        mist_d = f"M0,{my} "
        for x in range(0, WIDTH + 50, 50):
            my_ = my + math.sin(x * 0.003 + i) * 20 + rng.gauss(0, 5)
            mist_d += f"L{x},{my_} "
        mist_d += f"L{WIDTH},{my + 60} L0,{my + 60} Z"
        elements.append(path(mist_d, fill="#3a2818", opacity=0.08, filter="url(#mist)"))

    # swamp water surface
    water_y = y0 + 200
    water_d = f"M0,{water_y} "
    for x in range(0, WIDTH + 20, 20):
        wy = water_y + math.sin(x * 0.02) * 3 + rng.gauss(0, 1)
        water_d += f"L{x},{wy} "
    water_d += f"L{WIDTH},{y1} L0,{y1} Z"
    elements.append(path(water_d, fill="#0a0805", opacity=0.8))
    # water surface highlights
    for _ in range(40):
        rx = rng.uniform(0, WIDTH)
        ry = water_y + rng.uniform(-5, 30)
        elements.append(ellipse(rx, ry, rng.uniform(5, 20), 1, fill="#3a2818", opacity=0.15))

    # decaying roots / fallen trunks
    for i in range(6):
        rx = rng.uniform(0, WIDTH)
        ry = water_y + rng.uniform(-10, 40)
        rw = rng.uniform(60, 150)
        rh = rng.uniform(15, 30)
        elements.append(ellipse(rx, ry, rw, rh, fill="#1a0a04", opacity=0.6))
        # texture lines
        for t in range(3):
            elements.append(ellipse(rx, ry, rw * (0.4 + t * 0.2), rh * (0.4 + t * 0.2),
                                    fill="none", stroke="#2a1808", stroke_width=0.5, opacity=0.3))

    # methane bubbles rising from decay
    for _ in range(30):
        bx = rng.uniform(0, WIDTH)
        by = rng.uniform(water_y, y1)
        br = rng.uniform(2, 8)
        elements.append(circle(bx, by, br, fill="#3a2010", opacity=0.2, stroke="#5a3018", stroke_width=0.3))
        # bubble trail
        for t in range(3):
            elements.append(circle(bx + rng.uniform(-2, 2), by - (t + 1) * 10, br * (1 - t * 0.2),
                                    fill="#3a2010", opacity=0.1))

    # Tympanax — cartilage wheel creature
    tx, ty = WIDTH * 0.3, water_y + 60
    # tensegrity wheel
    elements.append(circle(tx, ty, 25, fill="none", stroke="#4a3020", stroke_width=2, opacity=0.6))
    for spoke in range(8):
        angle = spoke * math.pi / 4
        elements.append(line(tx, ty, tx + 25 * math.cos(angle), ty + 25 * math.sin(angle),
                              stroke="#3a2010", stroke_width=1, opacity=0.4))
    elements.append(circle(tx, ty, 4, fill="#6a4030", opacity=0.7))

    # Rooted Carillon — chitin bell spiral
    rcx, rcy = WIDTH * 0.7, water_y + 80
    for bell in range(5):
        bx = rcx + bell * 12
        by = rcy - bell * 15
        bw = 20 - bell * 2
        elements.append(ellipse(bx, by, bw, bw * 0.6, fill="#4a3020", opacity=0.5, stroke="#6a4030", stroke_width=0.5))

    # hanging vines / roots from above
    for i in range(15):
        vx = rng.uniform(0, WIDTH)
        vy = y0
        vl = rng.uniform(50, 150)
        vd = f"M{vx},{vy} Q{vx + rng.uniform(-10, 10)},{vy + vl / 2} {vx + rng.uniform(-20, 20)},{vy + vl}"
        elements.append(path(vd, stroke="#2a1808", stroke_width=1.5, fill="none", opacity=0.4))

    # floating particles — decomposers
    for _ in range(100):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(y0, y1)
        ps = rng.uniform(0.5, 2)
        elements.append(circle(px, py, ps, fill="#5a3018", opacity=rng.uniform(0.05, 0.2)))

    elements.append(text_el(30, y0 + 30, "MIRE", fill="#5a4030", font_size=14, font_family="serif",
                            letter_spacing=4, opacity=0.5))

    return group(elements, id="biome-mire")


def render_bone_fields() -> str:
    """Bone Fields: fossil-rich badlands, calcified remains."""
    y0, y1 = BIOME_BOUNDS["Bone Fields"]
    elements = []

    elements.append(rect(0, y0, WIDTH, y1 - y0, fill="url(#grad-bone)"))

    # rolling badlands terrain
    terrain_d = f"M0,{y1} "
    for x in range(0, WIDTH + 50, 30):
        ty = y0 + 150 + math.sin(x * 0.005) * 40 + math.sin(x * 0.02) * 15 + rng.gauss(0, 5)
        terrain_d += f"L{x},{ty} "
    terrain_d += f"L{WIDTH},{y1} Z"
    elements.append(path(terrain_d, fill="#3a2818", opacity=0.6))
    # second terrain layer
    terrain2_d = f"M0,{y1} "
    for x in range(0, WIDTH + 50, 40):
        ty = y0 + 250 + math.sin(x * 0.003 + 1) * 30 + rng.gauss(0, 8)
        terrain2_d += f"L{x},{ty} "
    terrain2_d += f"L{WIDTH},{y1} Z"
    elements.append(path(terrain2_d, fill="#2a1808", opacity=0.5))

    # fossil deposits — bone-like structures jutting from ground
    for i in range(15):
        bx = rng.uniform(0, WIDTH)
        by = y0 + rng.uniform(180, y1 - y0 - 20)
        bw = rng.uniform(8, 25)
        bh = rng.uniform(20, 80)

        # rib-like fossil
        fossil_d = f"M{bx},{by + bh} Q{bx - bw},{by + bh * 0.5} {bx},{by} "
        fossil_d += f"Q{bx + bw},{by + bh * 0.5} {bx},{by + bh} Z"
        col = rng.choice(["#5a4030", "#6a5038", "#4a3020"])
        elements.append(path(fossil_d, fill=col, opacity=0.5, stroke="#3a2010", stroke_width=0.5))

    # scattered bone fragments on ground
    for _ in range(60):
        fx = rng.uniform(0, WIDTH)
        fy = y0 + rng.uniform(200, y1 - y0)
        fw = rng.uniform(3, 12)
        fh = rng.uniform(2, 6)
        rot = rng.uniform(0, 360)
        col = rng.choice(["#6a5038", "#5a4030", "#7a6048"])
        elements.append(ellipse(fx, fy, fw, fh, fill=col, opacity=0.4,
                                transform=f"rotate({rot} {fx} {fy})"))

    # Knellhermit — cephalopod in a fossil skull
    kx, ky = WIDTH * 0.4, y0 + 280
    # skull shape
    skull_d = f"M{kx - 25},{ky + 15} Q{kx - 30},{ky - 15} {kx},{ky - 25} "
    skull_d += f"Q{kx + 30},{ky - 15} {kx + 25},{ky + 15} Q{kx + 15},{ky + 25} {kx},{ky + 20} "
    skull_d += f"Q{kx - 15},{ky + 25} {kx - 25},{ky + 15} Z"
    elements.append(path(skull_d, fill="#8a7050", opacity=0.6, stroke="#5a4030", stroke_width=1))
    # eye sockets
    elements.append(circle(kx - 10, ky - 5, 5, fill="#1a0a04"))
    elements.append(circle(kx + 10, ky - 5, 5, fill="#1a0a04"))
    # tentacles emerging from foramina
    for t in range(4):
        tx = kx + (t - 1.5) * 8
        td = f"M{tx},{ky + 20} Q{tx + rng.uniform(-15, 15)},{ky + 35} {tx + rng.uniform(-20, 20)},{ky + 50}"
        elements.append(path(td, stroke="#4a3020", stroke_width=1.5, fill="none", opacity=0.5))

    # Osteocast — six-legged creature with fossil armor
    ox, oy = WIDTH * 0.7, y0 + 220
    # legs
    for leg in range(6):
        lx = ox + (leg - 2.5) * 12
        elements.append(line(lx, oy, lx + (leg - 2.5) * 4, oy + 50,
                              stroke="#4a3020", stroke_width=1.5, stroke_linecap="round"))
    # body with fossil mosaic
    elements.append(ellipse(ox, oy, 20, 12, fill="#5a4030", opacity=0.7, stroke="#6a5038", stroke_width=0.5))
    # armor plates
    for p in range(5):
        px = ox + rng.uniform(-15, 15)
        py = oy + rng.uniform(-8, 5)
        elements.append(ellipse(px, py, rng.uniform(3, 6), rng.uniform(2, 4),
                                fill="#7a6048", opacity=0.5, stroke="#5a4030", stroke_width=0.3))

    # Marrowquern — larger creature with stratigraphic carapace
    mx2, my2 = WIDTH * 0.15, y0 + 300
    for leg in range(6):
        lx = mx2 + (leg - 2.5) * 18
        elements.append(line(lx, my2, lx + (leg - 2.5) * 6, my2 + 70,
                              stroke="#3a2010", stroke_width=2, stroke_linecap="round"))
    # domed carapace with strata
    elements.append(ellipse(mx2, my2 - 5, 35, 20, fill="#5a4030", opacity=0.6))
    for s in range(4):
        elements.append(ellipse(mx2, my2 - 5 - s * 4, 35 - s * 6, 20 - s * 4,
                                fill="none", stroke="#6a5038", stroke_width=0.5, opacity=0.4))

    # dust particles
    for _ in range(80):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(y0, y1)
        ps = rng.uniform(0.5, 1.5)
        elements.append(circle(px, py, ps, fill="#6a5038", opacity=rng.uniform(0.05, 0.2)))

    elements.append(text_el(30, y0 + 30, "BONE FIELDS", fill="#7a6048", font_size=14, font_family="serif",
                            letter_spacing=4, opacity=0.5))

    return group(elements, id="biome-bone-fields")


def render_glass_wastes() -> str:
    """Glass Wastes: crystalline desert, refractive, scorching."""
    y0, y1 = BIOME_BOUNDS["Glass Wastes"]
    elements = []

    elements.append(rect(0, y0, WIDTH, y1 - y0, fill="url(#grad-glass)"))

    # sun glow
    elements.append(circle(WIDTH * 0.7, y0 + 80, 120, fill="url(#sun-glow)", filter="url(#blur-heavy)"))
    elements.append(circle(WIDTH * 0.7, y0 + 80, 40, fill="#ffff80", opacity=0.6, filter="url(#glow-strong)"))

    # crystalline desert dunes
    for layer in range(3):
        dune_d = f"M0,{y1} "
        for x in range(0, WIDTH + 30, 25):
            dy = y0 + 100 + layer * 80 + math.sin(x * 0.004 + layer * 2) * 30 + math.sin(x * 0.015) * 10
            dune_d += f"L{x},{dy} "
        dune_d += f"L{WIDTH},{y1} Z"
        colors = ["#4a3010", "#3a2008", "#2a1808"]
        elements.append(path(dune_d, fill=colors[layer], opacity=0.5))

    # crystal formations — refractive prisms rising from the sand
    for i in range(12):
        cx = rng.uniform(50, WIDTH - 50)
        cy = y0 + rng.uniform(150, y1 - y0 - 30)
        h = rng.uniform(40, 100)
        w = rng.uniform(15, 30)

        # prism shape — triangular crystal
        prism_pts = [(cx - w, cy + h), (cx, cy), (cx + w, cy + h)]
        elements.append(polygon(prism_pts, fill="#6080a0", opacity=0.3, stroke="#a0c0e0", stroke_width=0.8))
        # internal facet
        elements.append(line(cx, cy, cx, cy + h, stroke="#80a0c0", stroke_width=0.5, opacity=0.3))
        # light refraction beam
        beam_angle = rng.uniform(-20, 20)
        elements.append(line(cx, cy, cx + beam_angle, cy - h * 0.3,
                              stroke="#ffff80", stroke_width=0.5, opacity=0.2, filter="url(#glow-soft"))
        # glow at tip
        elements.append(circle(cx, cy, w * 0.5, fill="url(#glow-yellow)", opacity=0.2, filter="url(#glow-soft)"))

    # Dioptra — lens creature focusing sunlight
    dx, dy = WIDTH * 0.3, y0 + 200
    # lens body
    elements.append(ellipse(dx, dy, 20, 15, fill="#80a0c0", opacity=0.3, stroke="#a0c0e0", stroke_width=0.5))
    # focused beam down to ground
    elements.append(path(f"M{dx - 15},{dy + 10} L{dx - 5},{dy + 60} L{dx + 5},{dy + 60} L{dx + 15},{dy + 10} Z",
                         fill="#ffff80", opacity=0.15, filter="url(#glow-soft)"))
    # scorch mark
    elements.append(ellipse(dx, dy + 62, 8, 2, fill="#1a0a00", opacity=0.5))
    # legs
    for leg in range(3):
        lx = dx + (leg - 1) * 15
        elements.append(line(lx, dy + 12, lx + (leg - 1) * 5, dy + 30,
                              stroke="#4a3010", stroke_width=1.5))

    # Heliocaster — stilt walker with parabolic mirror
    hx, hy = WIDTH * 0.6, y0 + 250
    for leg in range(6):
        lx = hx + (leg - 2.5) * 10
        elements.append(line(lx, hy, lx + (leg - 2.5) * 8, hy + 90,
                              stroke="#3a2008", stroke_width=1.5, stroke_linecap="round"))
    # parabolic mirror carapace
    body_pts = []
    for a in range(-90, 91, 10):
        bx = hx + a * 0.4
        by = hy - 15 + (a * a) * 0.002
        body_pts.append((bx, by))
    body_d = f"M{body_pts[0][0]},{body_pts[0][1]} "
    for px, py in body_pts[1:]:
        body_d += f"L{px},{py} "
    body_d += f"L{hx + 36},{hy} L{hx - 36},{hy} Z"
    elements.append(path(body_d, fill="#c0e0ff", opacity=0.25, stroke="#e0f0ff", stroke_width=0.5))
    # reflected light
    elements.append(path(f"M{hx},{hy - 15} L{hx - 25},{hy + 110} L{hx + 25},{hy + 110} Z",
                         fill="#ffff80", opacity=0.08, filter="url(#glow-soft)"))

    # heat shimmer (wavy lines)
    for _ in range(20):
        sx = rng.uniform(0, WIDTH)
        sy = y0 + rng.uniform(180, y1 - y0 - 20)
        shim_d = f"M{sx},{sy} "
        for s in range(8):
            sx2 = sx + s * 8
            sy2 = sy + math.sin(s * 0.5) * 3
            shim_d += f"L{sx2},{sy2} "
        elements.append(path(shim_d, stroke="#6a5028", stroke_width=0.3, fill="none", opacity=0.1))

    # glass shards scattered
    for _ in range(50):
        gx = rng.uniform(0, WIDTH)
        gy = y0 + rng.uniform(150, y1 - y0)
        gs = rng.uniform(2, 8)
        rot = rng.uniform(0, 180)
        elements.append(polygon([(gx, gy - gs), (gx + gs * 0.5, gy), (gx, gy + gs), (gx - gs * 0.5, gy)],
                                fill="#80a0c0", opacity=rng.uniform(0.1, 0.3),
                                stroke="#a0c0e0", stroke_width=0.2,
                                transform=f"rotate({rot} {gx} {gy})"))

    elements.append(text_el(30, y0 + 30, "GLASS WASTES", fill="#8a7050", font_size=14, font_family="serif",
                            letter_spacing=4, opacity=0.5))

    return group(elements, id="biome-glass-wastes")


def render_vent() -> str:
    """the Vent: thermal fissures, thermoelectric creatures, deep glow."""
    y0, y1 = BIOME_BOUNDS["the Vent"]
    elements = []

    elements.append(rect(0, y0, WIDTH, y1 - y0, fill="url(#grad-vent)"))

    # deep rock background
    rock_d = f"M0,{y1} "
    for x in range(0, WIDTH + 50, 40):
        ry = y0 + 50 + math.sin(x * 0.006) * 30 + rng.gauss(0, 10)
        rock_d += f"L{x},{ry} "
    rock_d += f"L{WIDTH},{y1} Z"
    elements.append(path(rock_d, fill="#1a0a05", opacity=0.7))

    # thermal fissures — glowing cracks in the rock
    for i in range(5):
        fx = rng.uniform(100, WIDTH - 100)
        fy_start = y0 + 60
        fissure_d = f"M{fx},{fy_start} "
        cy_f = fy_start
        cx_f = fx
        for j in range(10):
            cx_f += rng.uniform(-25, 25)
            cy_f += rng.uniform(15, 30)
            fissure_d += f"L{cx_f},{cy_f} "
        # glowing fissure
        elements.append(path(fissure_d, stroke="#ff6020", stroke_width=3, fill="none", opacity=0.6, filter="url(#glow-strong)"))
        elements.append(path(fissure_d, stroke="#ffa040", stroke_width=1, fill="none", opacity=0.8))
        # thermal glow around fissure
        elements.append(path(fissure_d, stroke="#ff4010", stroke_width=15, fill="none", opacity=0.1, filter="url(#blur-heavy)"))

    # large thermal glow sources
    for _ in range(6):
        gx = rng.uniform(50, WIDTH - 50)
        gy = rng.uniform(y0 + 100, y1 - 50)
        gr = rng.uniform(60, 120)
        elements.append(circle(gx, gy, gr, fill="url(#thermal-glow)", opacity=0.3, filter="url(#blur-heavy)"))

    # mineral chimney columns — thermoelectric creatures
    for i in range(10):
        cx = rng.uniform(80, WIDTH - 80)
        cy_base = y1 - rng.uniform(10, 60)
        ch = rng.uniform(60, 160)
        cw = rng.uniform(12, 25)

        # stacked mineral discs
        n_discs = int(ch / 8)
        for d in range(n_discs):
            dy = cy_base - d * 8
            dw = cw + math.sin(d * 0.3) * 3
            col = rng.choice(["#4a3020", "#5a3828", "#3a2818", "#6a4830"])
            elements.append(ellipse(cx, dy, dw, 4, fill=col, opacity=0.7, stroke="#2a1808", stroke_width=0.3))

        # thermoelectric glow — bimetallic rings
        for g in range(0, n_discs, 3):
            gy_disc = cy_base - g * 8
            elements.append(ellipse(cx, gy_disc, cw + 2, 2, fill="#ff6020", opacity=0.3, filter="url(#glow-soft)"))

        # top glow — plume
        elements.append(circle(cx, cy_base - ch, cw * 1.5, fill="url(#thermal-glow)", opacity=0.2, filter="url(#glow-soft)"))

        # electrical discharge between chimneys
        if i > 0 and rng.random() < 0.3:
            prev_cx = cx - 150 + rng.uniform(-30, 30)
            prev_cy = cy_base - ch * 0.5
            arc_d = f"M{prev_cx},{prev_cy} Q{(prev_cx + cx) / 2},{min(prev_cy, cy_base - ch * 0.5) - 30} {cx},{cy_base - ch * 0.5}"
            elements.append(path(arc_d, stroke="#ffa040", stroke_width=0.5, fill="none", opacity=0.3, filter="url(#glow-soft)"))

    # Bismuth Flue — spiral crystal lamellae
    bx, by = WIDTH * 0.25, y1 - 100
    for ring in range(15):
        angle = ring * 0.4
        r = 5 + ring * 2
        rx = bx + r * math.cos(angle)
        ry = by + r * math.sin(angle) - ring * 3
        col = rng.choice(["#8060a0", "#a080c0", "#6050a0", "#c0a0e0"])
        elements.append(ellipse(rx, ry, r * 0.6, r * 0.2, fill=col, opacity=0.3,
                                transform=f"rotate({math.degrees(angle)} {rx} {ry})"))
    elements.append(circle(bx, by - 45, 8, fill="url(#glow-purple)", opacity=0.3, filter="url(#glow-soft)"))

    # Seebeck stave — thermopile rod
    sx, sy = WIDTH * 0.5, y1 - 200
    for seg in range(12):
        sy_s = sy + seg * 15
        col = "#3a2010" if seg % 2 == 0 else "#5a3020"
        elements.append(rect(sx - 4, sy_s, 8, 14, fill=col, opacity=0.7))
        # junction glow
        elements.append(rect(sx - 5, sy_s + 13, 10, 2, fill="#ff6020", opacity=0.4, filter="url(#glow-soft)"))
    elements.append(circle(sx, sy, 15, fill="url(#thermal-glow)", opacity=0.2, filter="url(#glow-soft)"))

    # Resonotheca — resonant mineral tube colony
    rx2, ry2 = WIDTH * 0.75, y1 - 150
    for tube in range(8):
        tx = rx2 + (tube - 3.5) * 10
        ty = ry2 + rng.uniform(-20, 20)
        th = rng.uniform(40, 80)
        tw = rng.uniform(4, 8)
        elements.append(rect(tx - tw / 2, ty - th, tw, th, fill="#3a2818", opacity=0.6, stroke="#5a4030", stroke_width=0.3))
        elements.append(ellipse(tx, ty - th, tw, 2, fill="#ff6020", opacity=0.3, filter="url(#glow-soft)"))

    # rising heat plumes / bubbles
    for _ in range(60):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(y0 + 100, y1)
        ps = rng.uniform(1, 4)
        elements.append(circle(px, py, ps, fill="#ff6020", opacity=rng.uniform(0.05, 0.15)))

    # mineral particles
    for _ in range(80):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(y0, y1)
        ps = rng.uniform(0.5, 2)
        col = rng.choice(["#4a3020", "#5a4030", "#3a2818"])
        elements.append(circle(px, py, ps, fill=col, opacity=rng.uniform(0.1, 0.3)))

    elements.append(text_el(30, y0 + 30, "THE VENT", fill="#ff6020", font_size=14, font_family="serif",
                            letter_spacing=4, opacity=0.6))

    return group(elements, id="biome-vent")


# ---------------------------------------------------------------------------
# transition zones between biomes
# ---------------------------------------------------------------------------


def render_transitions() -> str:
    """Soft transition zones between biome boundaries."""
    elements = []
    transitions = [
        (380, 420, "#1a2040", "#1a2818"),   # Rime -> Aether
        (780, 820, "#1a2818", "#2a3818"),   # Aether -> Canopy
        (1180, 1220, "#15200a", "#0a0815"), # Canopy -> Underglow
        (1580, 1620, "#080612", "#0e0a0a"), # Underglow -> Mire
        (1980, 2020, "#1a1208", "#2a2018"), # Mire -> Bone Fields
        (2380, 2420, "#382818", "#3a3010"), # Bone Fields -> Glass Wastes
        (2780, 2820, "#2a1808", "#2a1808"), # Glass Wastes -> Vent
    ]
    for y_top, y_bot, c1, c2 in transitions:
        elements.append(rect(0, y_top, WIDTH, y_bot - y_top,
                              fill=c1, opacity=0.3, filter="url(#blur-heavy)"))
    return group(elements, id="transitions")


# ---------------------------------------------------------------------------
# master assembly
# ---------------------------------------------------------------------------


def render_light_shafts() -> str:
    """Light shafts piercing through biome boundaries."""
    elements = []

    # light from above through Rime into Aether
    for i in range(5):
        lx = rng.uniform(100, WIDTH - 100)
        shaft_d = f"M{lx},0 L{lx + 30},400 L{lx + 50},800 L{lx + 20},0 Z"
        elements.append(path(shaft_d, fill="#ffffff", opacity=0.02, filter="url(#blur-heavy)"))

    # light from Canopy down into Underglow
    for i in range(4):
        lx = rng.uniform(100, WIDTH - 100)
        shaft_d = f"M{lx - 20},800 L{lx + 20},800 L{lx + 40},1200 L{lx - 40},1200 Z"
        elements.append(path(shaft_d, fill="#ffd060", opacity=0.03, filter="url(#blur-heavy)"))

    # thermal uplight from Vent
    for i in range(5):
        lx = rng.uniform(100, WIDTH - 100)
        shaft_d = f"M{lx - 15},2800 L{lx + 15},2800 L{lx + 35},3200 L{lx - 35},3200 Z"
        elements.append(path(shaft_d, fill="#ff6020", opacity=0.04, filter="url(#blur-heavy)"))

    return group(elements, id="light-shafts")


def render_depth_fog() -> str:
    """Atmospheric depth fog at biome boundaries."""
    elements = []

    fog_zones = [
        (380, 420, "#1a2040", 0.15),
        (780, 820, "#2a1848", 0.12),
        (1180, 1220, "#15200a", 0.1),
        (1580, 1620, "#080612", 0.1),
        (1980, 2020, "#1a1208", 0.12),
        (2380, 2420, "#382818", 0.1),
        (2780, 2820, "#2a1808", 0.1),
    ]

    for y_top, y_bot, color, opacity in fog_zones:
        # wavy fog band
        fog_d = f"M0,{y_top} "
        for x in range(0, WIDTH + 40, 40):
            fy = (y_top + y_bot) / 2 + math.sin(x * 0.005) * 10 + rng.gauss(0, 3)
            fog_d += f"L{x},{fy} "
        fog_d += f"L{WIDTH},{y_bot} L0,{y_bot} Z"
        elements.append(path(fog_d, fill=color, opacity=opacity, filter="url(#mist)"))

    return group(elements, id="depth-fog")


def render_ambient_particles() -> str:
    """Ambient particles floating across all biomes — spores, dust, motes."""
    elements = []

    # ice crystals in Rime and Aether
    for _ in range(80):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(0, 800)
        ps = rng.uniform(1, 3)
        rot = rng.uniform(0, 90)
        col = rng.choice(["#a0d0ff", "#c0e0ff", "#ffffff"])
        elements.append(polygon([(px, py - ps), (px + ps * 0.4, py), (px, py + ps), (px - ps * 0.4, py)],
                                fill=col, opacity=rng.uniform(0.1, 0.3),
                                stroke="#80a0c0", stroke_width=0.2,
                                transform=f"rotate({rot} {px} {py})"))

    # bioluminescent spores in Underglow
    for _ in range(120):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(1200, 1600)
        ps = rng.uniform(0.5, 2.5)
        col = rng.choice(["#80ff40", "#40ffa0", "#60d0ff", "#c0a0ff"])
        elements.append(circle(px, py, ps, fill=col, opacity=rng.uniform(0.2, 0.5), filter="url(#glow-soft)"))

    # dust in Bone Fields and Glass Wastes
    for _ in range(100):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(2000, 2800)
        ps = rng.uniform(0.5, 2)
        col = rng.choice(["#6a5038", "#8a7050", "#7a6048"])
        elements.append(circle(px, py, ps, fill=col, opacity=rng.uniform(0.05, 0.2)))

    # thermal motes in the Vent
    for _ in range(80):
        px = rng.uniform(0, WIDTH)
        py = rng.uniform(2800, 3200)
        ps = rng.uniform(1, 3)
        col = rng.choice(["#ff6020", "#ffa040", "#ff8030"])
        elements.append(circle(px, py, ps, fill=col, opacity=rng.uniform(0.05, 0.2), filter="url(#glow-soft)"))

    return group(elements, id="ambient-particles")


def render_border_decoration() -> str:
    """Decorative border with biome markers."""
    elements = []

    # outer frame
    elements.append(rect(8, 8, WIDTH - 16, HEIGHT - 16, fill="none",
                          stroke="#3a3020", stroke_width=1, opacity=0.4))
    elements.append(rect(12, 12, WIDTH - 24, HEIGHT - 24, fill="none",
                          stroke="#3a3020", stroke_width=0.5, opacity=0.2))

    # corner ornaments
    corner_size = 30
    for cx, cy in [(12, 12), (WIDTH - 12, 12), (12, HEIGHT - 12), (WIDTH - 12, HEIGHT - 12)]:
        dx = 1 if cx < WIDTH / 2 else -1
        dy = 1 if cy < HEIGHT / 2 else -1
        elements.append(path(
            f"M{cx + dx * corner_size},{cy} L{cx},{cy} L{cx},{cy + dy * corner_size}",
            stroke="#5a4830", stroke_width=1, fill="none", opacity=0.5
        ))
        elements.append(circle(cx + dx * 5, cy + dy * 5, 2, fill="#5a4830", opacity=0.4))

    # biome divider lines with small diamonds
    for y_top, _, _, _ in [
        (400, 420, "", 0), (800, 820, "", 0), (1200, 1220, "", 0),
        (1600, 1620, "", 0), (2000, 2020, "", 0), (2400, 2420, "", 0), (2800, 2820, "", 0)
    ]:
        elements.append(line(12, y_top, 30, y_top, stroke="#5a4830", stroke_width=0.5, opacity=0.4))
        elements.append(polygon([(20, y_top - 3), (23, y_top), (20, y_top + 3), (17, y_top)],
                                fill="#5a4830", opacity=0.3))
        elements.append(line(WIDTH - 30, y_top, WIDTH - 12, y_top,
                              stroke="#5a4830", stroke_width=0.5, opacity=0.4))
        elements.append(polygon([(WIDTH - 20, y_top - 3), (WIDTH - 17, y_top),
                                  (WIDTH - 20, y_top + 3), (WIDTH - 23, y_top)],
                                fill="#5a4830", opacity=0.3))

    # title plate at top
    title_bg = rect(WIDTH / 2 - 120, 8, 240, 24, fill="#0a0a0a", opacity=0.6, stroke="#3a3020", stroke_width=0.5)
    title_text = text_el(WIDTH / 2, 24, "BESTIARY OF THE DRIFT",
                          fill="#a09080", font_size=10, font_family="serif",
                          text_anchor="middle", letter_spacing=6, opacity=0.6)

    # subtitle at bottom
    sub_text = text_el(WIDTH / 2, HEIGHT - 14, "— A Cross-Section of an Alien World —",
                       fill="#5a4830", font_size=8, font_family="serif",
                       text_anchor="middle", letter_spacing=4, opacity=0.4)

    elements.extend([title_bg, title_text, sub_text])
    return group(elements, id="border-decoration")


def render_creature_details() -> str:
    """Additional detailed creatures with intricate anatomy."""
    elements = []

    # Rime: detailed Cryostele ice spire
    cx, cy = 1100, 150
    for ring in range(20):
        angle = ring * 0.5
        r = 8 + ring * 1.5
        rx = cx + r * math.cos(angle)
        ry = cy + ring * 12
        elements.append(ellipse(rx, ry, r * 0.7, r * 0.2, fill="#60a0d0", opacity=0.2,
                                transform=f"rotate({math.degrees(angle)} {rx} {ry})"))
        if ring % 3 == 0:
            elements.append(circle(rx, ry, 2, fill="#60d0ff", opacity=0.5, filter="url(#glow-soft)"))
    elements.append(circle(cx, cy + 100, 30, fill="url(#glow-cyan)", opacity=0.1, filter="url(#blur-heavy)"))

    # Aether: detailed Aerochorda with trailing net
    ax, ay = 1200, 500
    n_b = 12
    for j in range(n_b):
        bx = ax + math.sin(j * 0.4) * 20
        by = ay + j * 22
        elements.append(ellipse(bx, by, 18, 12, fill="#60d0ff", opacity=0.25, stroke="#80e0ff", stroke_width=0.4))
        elements.append(ellipse(bx - 5, by - 3, 6, 3, fill="#ffffff", opacity=0.15))
        elements.append(ellipse(bx, by, 10, 6, fill="none", stroke="#80e0ff", stroke_width=0.2, opacity=0.2))
    net_top = ay + n_b * 22
    for k in range(20):
        nx = ax + rng.uniform(-80, 80)
        ny = net_top + rng.uniform(5, 120)
        elements.append(line(ax, net_top, nx, ny, stroke="#80e0ff", stroke_width=0.2, opacity=0.12))
        elements.append(circle(nx, ny, 0.8, fill="#a0d0ff", opacity=0.3))
    for k in range(15):
        x1 = ax + rng.uniform(-60, 60)
        y1 = net_top + rng.uniform(10, 100)
        x2 = ax + rng.uniform(-60, 60)
        y2 = net_top + rng.uniform(10, 100)
        d = math.hypot(x2 - x1, y2 - y1)
        if d < 40:
            elements.append(line(x1, y1, x2, y2, stroke="#80e0ff", stroke_width=0.15, opacity=0.08))

    # Canopy: Cymesail kite creature
    kx, ky = 1300, 950
    kite_pts = [(kx, ky - 30), (kx + 25, ky), (kx, ky + 15), (kx - 25, ky)]
    elements.append(polygon(kite_pts, fill="#4a6020", opacity=0.4, stroke="#6a8030", stroke_width=0.5))
    elements.append(path(f"M{kx},{ky + 15} Q{kx - 10},{ky + 100} {kx},{ky + 200}",
                         stroke="#3a5018", stroke_width=1, fill="none", opacity=0.4))
    for _ in range(8):
        sx = kx + rng.uniform(-20, 20)
        sy = ky + rng.uniform(-20, 10)
        elements.append(circle(sx, sy, 2, fill="#80a040", opacity=0.3))

    # Underglow: detailed fungal column with gills
    fx, fy = 200, 1450
    elements.append(path(f"M{fx - 6},{fy + 80} Q{fx - 10},{fy + 40} {fx - 6},{fy} L{fx + 6},{fy} Q{fx + 10},{fy + 40} {fx + 6},{fy + 80} Z",
                         fill="#2a1a30", opacity=0.8))
    cap_d = f"M{fx - 50},{fy} Q{fx},{fy - 30} {fx + 50},{fy} Q{fx + 40},{fy + 8} {fx},{fy + 10} Q{fx - 40},{fy + 8} {fx - 50},{fy} Z"
    elements.append(path(cap_d, fill="#4a2080", opacity=0.6, stroke="#6030a0", stroke_width=0.5))
    for g in range(12):
        gx = fx - 45 + g * 8
        elements.append(path(f"M{gx},{fy + 2} L{gx + 2},{fy + 12}", stroke="#80ff40", stroke_width=0.5, opacity=0.15))
    for _ in range(6):
        sx = fx + rng.uniform(-40, 40)
        sy = fy + rng.uniform(-20, 5)
        elements.append(circle(sx, sy, rng.uniform(1.5, 3), fill="#80ff40", opacity=0.5, filter="url(#glow-soft)"))

    # Mire: detailed Baryscaphe diving-bell chain
    bx2, by2 = 1300, 1750
    for seg in range(8):
        sx = bx2 + math.sin(seg * 0.6) * 10
        sy = by2 + seg * 18
        elements.append(ellipse(sx, sy, 10, 7, fill="#3a2010", opacity=0.4, stroke="#5a3018", stroke_width=0.3))
        elements.append(ellipse(sx, sy - 2, 5, 3, fill="#5a3018", opacity=0.2))
    for b in range(6):
        elements.append(circle(bx2 + rng.uniform(-5, 5), by2 - b * 15, rng.uniform(2, 5),
                               fill="#3a2010", opacity=0.15, stroke="#5a3018", stroke_width=0.2))

    # Bone Fields: detailed Marrowquern with strata
    mx3, my3 = 1300, 2150
    for leg in range(6):
        lx = mx3 + (leg - 2.5) * 20
        elements.append(line(lx, my3, lx + (leg - 2.5) * 8, my3 + 80,
                             stroke="#3a2010", stroke_width=2.5, stroke_linecap="round"))
    for s in range(8):
        sw = 45 - s * 5
        sh = 25 - s * 3
        col = rng.choice(["#6a5038", "#7a6048", "#5a4030", "#8a7058"])
        elements.append(ellipse(mx3, my3 - s * 5, sw, sh, fill=col, opacity=0.5, stroke="#4a3020", stroke_width=0.3))
        for _ in range(rng.randint(2, 5)):
            fx2 = mx3 + rng.uniform(-sw * 0.7, sw * 0.7)
            fy2 = my3 - s * 5 + rng.uniform(-sh * 0.5, sh * 0.3)
            elements.append(ellipse(fx2, fy2, rng.uniform(1, 3), rng.uniform(0.5, 2), fill="#8a7058", opacity=0.4))

    # Glass Wastes: detailed Dioptra with lens
    dx2, dy2 = 500, 2550
    elements.append(ellipse(dx2, dy2, 25, 18, fill="#80a0c0", opacity=0.25, stroke="#a0c0e0", stroke_width=0.5))
    for r in range(5):
        elements.append(ellipse(dx2, dy2, 22 - r * 4, 16 - r * 3, fill="none", stroke="#a0c0e0", stroke_width=0.3, opacity=0.2))
    elements.append(path(f"M{dx2 - 18},{dy2 + 12} L{dx2 - 8},{dy2 + 80} L{dx2 + 8},{dy2 + 80} L{dx2 + 18},{dy2 + 12} Z",
                         fill="#ffff80", opacity=0.12, filter="url(#glow-soft)"))
    elements.append(circle(dx2, dy2 + 80, 4, fill="#ffffff", opacity=0.4, filter="url(#glow-strong)"))
    elements.append(circle(dx2, dy2 + 80, 12, fill="#ffff80", opacity=0.15, filter="url(#blur-heavy)"))
    for leg in range(3):
        lx = dx2 + (leg - 1) * 18
        elements.append(line(lx, dy2 + 15, lx + (leg - 1) * 6, dy2 + 35, stroke="#4a3010", stroke_width=2, stroke_linecap="round"))

    # the Vent: detailed Galvanoskein thermocouple braid
    vx, vy = 500, 2950
    for strand in range(4):
        offset = (strand - 1.5) * 6
        sd = f"M{vx + offset},{vy} "
        for s in range(20):
            sx = vx + offset + math.sin(s * 0.4 + strand) * 8
            sy = vy + s * 12
            sd += f"L{sx},{sy} "
        col = "#4a3020" if strand % 2 == 0 else "#6a4830"
        elements.append(path(sd, stroke=col, stroke_width=2, fill="none", opacity=0.5))
    for j in range(10):
        jx = vx + math.sin(j * 0.8) * 8
        jy = vy + j * 24
        elements.append(circle(jx, jy, 3, fill="#ff6020", opacity=0.5, filter="url(#glow-soft)"))
        elements.append(circle(jx, jy, 8, fill="#ff6020", opacity=0.1, filter="url(#blur-heavy)"))
    for _ in range(8):
        cx2 = vx + rng.uniform(-15, 15)
        cy2 = vy + rng.uniform(0, 240)
        elements.append(circle(cx2, cy2, rng.uniform(2, 5), fill="#c08040", opacity=0.2))

    return group(elements, id="creature-details")


def generate() -> str:
    layers = [
        defs_section(),
        render_rime(),
        render_aether(),
        render_canopy(),
        render_underglow(),
        render_mire(),
        render_bone_fields(),
        render_glass_wastes(),
        render_vent(),
        render_light_shafts(),
        render_creature_details(),
        render_ambient_particles(),
        render_depth_fog(),
        render_border_decoration(),
    ]

    svg_attrs = {
        "xmlns": "http://www.w3.org/2000/svg",
        "viewBox": f"0 0 {WIDTH} {HEIGHT}",
        "width": WIDTH,
        "height": HEIGHT,
    }

    svg_content = "".join(layers)
    return el("svg", svg_attrs, [svg_content])


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    svg = generate()
    OUTPUT.write_text(svg)
    print(f"wrote {OUTPUT} ({len(svg)} bytes, {svg.count(chr(10))} lines)")


if __name__ == "__main__":
    main()
