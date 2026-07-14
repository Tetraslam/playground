"""sunforge near layer (Blender-side): corridor cells as real geometry.

bpy + bundled numpy + stdlib ONLY. Consumes renders/data/corridor.npz +
ca.npz; builds one small mesh per corridor cell from its exact dual polygon
(corners shared with neighbors -> seamless tiling):

  TRUSS  skeletal frame: ring beams at two levels, corner pylons, spokes,
         plus ember work lamps (the frontier glows)
  PLATE  low slab + sparse equipment boxes; some cells grow radiator fin
         rows with a dull furnace glow
  LIVE   slab + a block of towers, window speckle in the shader
  pentagon cells become foundry spires (stacked, beaconed) — landmarks

Faces are bucketed per material (metal / lamp / city / radiator) into up to
two objects per cell. Deterministic per (seed, cell id).
"""

from __future__ import annotations

import bpy
import numpy as np

SHELL_R = 2000.0

Bucket = tuple[list[list[float]], list[list[int]]]


def _bucket(d: dict[str, Bucket], name: str) -> Bucket:
    if name not in d:
        d[name] = ([], [])
    return d[name]


def _box(b: Bucket, origin: np.ndarray, ax: np.ndarray, ay: np.ndarray, az: np.ndarray) -> None:
    """Parallelepiped: origin corner + three edge vectors."""
    verts, faces = b
    i = len(verts)
    for cz in (0, 1):
        for cy in (0, 1):
            for cx in (0, 1):
                verts.append(list(origin + cx * ax + cy * ay + cz * az))
    quads = [
        (0, 1, 3, 2),
        (4, 6, 7, 5),
        (0, 2, 6, 4),
        (1, 5, 7, 3),
        (0, 4, 5, 1),
        (2, 3, 7, 6),
    ]
    faces.extend([[i + a, i + b_, i + c, i + d] for a, b_, c, d in quads])


def _beam(b: Bucket, p0: np.ndarray, p1: np.ndarray, w: float, up: np.ndarray) -> None:
    """Square strut from p0 to p1, w wide, oriented against `up`."""
    axis = p1 - p0
    length = np.linalg.norm(axis)
    if length < 1e-6:
        return
    a = axis / length
    s = np.cross(a, up)
    if np.linalg.norm(s) < 1e-6:
        s = np.cross(a, np.array([1.0, 0.0, 0.0]))
    s /= np.linalg.norm(s)
    t = np.cross(a, s)
    _box(b, p0 - 0.5 * w * (s + t), axis, w * s, w * t)


def _prism(b: Bucket, dirs: np.ndarray, h0: float, h1: float) -> None:
    """Polygon slab: cell corner dirs extruded radially from R+h0 to R+h1."""
    verts, faces = b
    i = len(verts)
    n = len(dirs)
    for h in (h0, h1):
        verts.extend((dirs * (SHELL_R + h)).tolist())
    faces.append([i + k for k in range(n - 1, -1, -1)])  # bottom (inward)
    faces.append([i + n + k for k in range(n)])  # top
    faces.extend([[i + k, i + (k + 1) % n, i + n + (k + 1) % n, i + n + k] for k in range(n)])


def _frame_at(center_dir: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Local tangent frame (t1, t2, up) at a unit direction."""
    up = center_dir / np.linalg.norm(center_dir)
    ref = np.array([0.0, 0.0, 1.0]) if abs(up[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    t1 = np.cross(ref, up)
    t1 /= np.linalg.norm(t1)
    return t1, np.cross(up, t1), up


# ------------------------------------------------------------------ cell kits
def truss_cell(bk: dict[str, Bucket], dirs: np.ndarray, cd: np.ndarray, prog: float, rng) -> None:
    metal, lamp = _bucket(bk, "metal"), _bucket(bk, "lamp")
    t1, t2, up = _frame_at(cd)
    lo = dirs * (SHELL_R + 1.0)
    hi = dirs * (SHELL_R + 8.0)
    top = cd * (SHELL_R + 10.0)
    n = len(dirs)
    for k in range(n):
        _beam(metal, lo[k], lo[(k + 1) % n], 1.2, up)  # lower ring
        _beam(metal, lo[k], hi[k], 1.0, up)  # pylons
        _beam(metal, lo[k], hi[(k + 1) % n], 0.6, up)  # diagonal braces
        if prog > 0.35:
            _beam(metal, hi[k], hi[(k + 1) % n], 1.2, up)  # upper ring
        if prog > 0.65:
            _beam(metal, hi[k], top, 0.7, up)  # spokes
    _beam(metal, cd * SHELL_R, top, 1.6, up)  # center pylon
    for _ in range(rng.integers(2, 5)):
        k = int(rng.integers(0, n))
        p = lo[k] + up * rng.uniform(1.0, 7.0)
        _box(lamp, p, 0.9 * t1, 0.9 * t2, 0.9 * up)


def plate_cell(bk: dict[str, Bucket], dirs: np.ndarray, cd: np.ndarray, prog: float, rng) -> None:
    metal = _bucket(bk, "metal")
    _prism(metal, dirs, 0.0, 3.0)
    t1, t2, up = _frame_at(cd)
    base = cd * (SHELL_R + 3.0)
    span = 14.0
    for _ in range(int(rng.integers(0, 4))):  # equipment boxes
        off = rng.uniform(-span, span, 2)
        e = rng.uniform(1.5, 4.0, 3)
        _box(metal, base + off[0] * t1 + off[1] * t2, e[0] * t1, e[1] * t2, e[2] * up)
    if rng.random() < 0.35 and prog > 0.3:  # radiator fin row, furnace-dull
        rad = _bucket(bk, "radiator")
        k = int(rng.integers(4, 7))
        f0 = base + rng.uniform(-8, 8) * t1 - 0.5 * k * 3.2 * t2
        for j in range(k):
            _box(rad, f0 + j * 3.2 * t2, 9.0 * t1, 0.35 * t2, 6.5 * up)


def live_cell(bk: dict[str, Bucket], dirs: np.ndarray, cd: np.ndarray, rng) -> None:
    metal, city = _bucket(bk, "metal"), _bucket(bk, "city")
    _prism(metal, dirs, 0.0, 3.0)
    t1, t2, up = _frame_at(cd)
    base = cd * (SHELL_R + 3.0)
    for _ in range(int(rng.integers(4, 10))):
        off = rng.uniform(-13.0, 13.0, 2)
        w, d = rng.uniform(2.0, 5.0, 2)
        h = rng.uniform(5.0, 18.0) * (1.6 if rng.random() < 0.12 else 1.0)
        p = base + off[0] * t1 + off[1] * t2
        _box(city, p - 0.5 * w * t1 - 0.5 * d * t2, w * t1, d * t2, h * up)


def foundry_cell(bk: dict[str, Bucket], dirs: np.ndarray, cd: np.ndarray, rng) -> None:
    metal, lamp = _bucket(bk, "metal"), _bucket(bk, "lamp")
    _prism(metal, dirs, 0.0, 4.0)
    t1, t2, up = _frame_at(cd)
    base = cd * SHELL_R
    for lvl, (hw, h) in enumerate([(9.0, 16.0), (6.0, 30.0), (3.0, 44.0)]):
        z0 = 4.0 + (0 if lvl == 0 else [16.0, 30.0][lvl - 1])
        _box(metal, base + z0 * up - hw * t1 - hw * t2, 2 * hw * t1, 2 * hw * t2, (h - z0) * up)
    _box(lamp, base + 45.0 * up - 1.2 * t1 - 1.2 * t2, 2.4 * t1, 2.4 * t2, 2.4 * up)


# ------------------------------------------------------------------ materials
def _mat_metal() -> bpy.types.Material:
    m = bpy.data.materials.new("near_metal")
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.015, 0.017, 0.022, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.85
    bsdf.inputs["Roughness"].default_value = 0.45
    return m


def _mat_lamp() -> bpy.types.Material:
    m = bpy.data.materials.new("ember_lamp")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.3, 0.06, 1.0)
    em.inputs["Strength"].default_value = 25.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def _mat_radiator() -> bpy.types.Material:
    m = bpy.data.materials.new("radiator")
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.05, 0.02, 0.015, 1.0)
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.08, 0.012, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 1.0
    return m


def _mat_city() -> bpy.types.Material:
    """Dark towers with warm window speckle from world-space noise."""
    m = bpy.data.materials.new("city_struct")
    m.use_nodes = True
    nt = m.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.02, 0.022, 0.028, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.4
    bsdf.inputs["Roughness"].default_value = 0.6
    tex = nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = 0.9
    tex.inputs["Detail"].default_value = 3.0
    geo = nodes.new("ShaderNodeNewGeometry")
    links.new(geo.outputs["Position"], tex.inputs["Vector"])
    gate = nodes.new("ShaderNodeMath")
    gate.operation = "GREATER_THAN"
    gate.inputs[1].default_value = 0.62
    links.new(tex.outputs["Fac"], gate.inputs[0])
    strength = nodes.new("ShaderNodeMath")
    strength.operation = "MULTIPLY"
    strength.inputs[1].default_value = 2.2
    links.new(gate.outputs[0], strength.inputs[0])
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.72, 0.38, 1.0)
    links.new(strength.outputs[0], bsdf.inputs["Emission Strength"])
    return m


# ---------------------------------------------------------------- entry point
def build_near_layer(data_dir, frame: int, seed: int = 7) -> int:
    cor = np.load(data_dir / "corridor.npz")
    ca = np.load(data_dir / "ca.npz")
    lat = np.load(data_dir / "lattice.npz")
    ids, offsets, corners = cor["ids"], cor["offsets"], cor["corners"]
    centers = lat["centers"].astype(np.float64)
    pentagons = set(int(p) for p in lat["pentagons"])

    t_t, t_p, t_l = ca["t_truss"][ids], ca["t_plate"][ids], ca["t_live"][ids]
    prog_t = np.clip((frame - t_t) / np.maximum(t_p - t_t, 1e-3), 0, 1)

    mats = {
        "metal": _mat_metal(),
        "lamp": _mat_lamp(),
        "radiator": _mat_radiator(),
        "city": _mat_city(),
    }
    coll = bpy.data.collections.new("near_layer")
    bpy.context.scene.collection.children.link(coll)

    built = 0
    for i, cell in enumerate(ids):
        if t_t[i] > frame:
            continue  # VOID: nothing yet
        dirs = corners[offsets[i] : offsets[i + 1]].astype(np.float64)
        cd = centers[cell]
        rng = np.random.default_rng((seed << 20) ^ int(cell))
        bk: dict[str, Bucket] = {}
        if int(cell) in pentagons:
            foundry_cell(bk, dirs, cd, rng)
        elif t_l[i] <= frame:
            live_cell(bk, dirs, cd, rng)
        elif t_p[i] <= frame:
            plate_cell(bk, dirs, cd, float(prog_t[i]), rng)
        else:
            truss_cell(bk, dirs, cd, float(prog_t[i]), rng)
        for bucket_name, (verts, faces) in bk.items():
            mesh = bpy.data.meshes.new(f"cell_{cell}_{bucket_name}")
            mesh.from_pydata(verts, [], faces)
            mesh.materials.append(mats[bucket_name])
            ob = bpy.data.objects.new(mesh.name, mesh)
            coll.objects.link(ob)
        built += 1
    return built
