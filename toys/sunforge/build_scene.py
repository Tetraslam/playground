"""sunforge stage 2 (Blender-side): renders/data/ -> renders/shell.blend.

Run via:  tools/blender.sh run toys/sunforge/build_scene.py -- [--frame 1]

bpy + bundled numpy + stdlib ONLY (house rule). M2 scope: the far layer —
whole-shell sphere whose shader decodes the statemap (R=state, G=progress,
B=city field; equirect per sim/statemaps.py convention), the star + its
light, a procedural starfield world, hero camera, bloom compositor.
M3 adds the corridor greebles, M4 the cockpit rig + statemap sequencing.
"""

import argparse
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).parent))
from greebles import build_near_layer  # noqa: E402

TOY = Path(__file__).parent
DATA = TOY / "renders" / "data"

SHELL_R = 2000.0
STAR_R = 250.0
FPS = 24
N_FRAMES = 2880
STATEMAP_EVERY = 24

EMBER = (1.0, 0.28, 0.05, 1.0)  # truss worklights
CITY = (1.0, 0.72, 0.38, 1.0)  # city lights
FURNACE = (1.0, 0.55, 0.25, 1.0)  # shell inner face
STAR_COLOR = (1.0, 0.62, 0.32, 1.0)


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", type=int, default=1, help="film frame to stage")
    ap.add_argument("--out", type=Path, default=TOY / "renders" / "shell.blend")
    ap.add_argument(
        "--shot",
        default="film",
        choices=("film", "hero", "s2", "s3"),
        help="film = the ship rig on path.npz; hero/s2/s3 = static staged stills",
    )
    ap.add_argument("--seed", type=int, default=7)
    return ap.parse_args(argv)


def wipe() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def first_statemap() -> Path:
    """statemap_0001.png — the sequence anchor (maps are indexed 1..120)."""
    p = DATA / "statemap_0001.png"
    if not p.exists():
        raise FileNotFoundError("no statemaps — run gen_scene.py first")
    return p


# ---------------------------------------------------------------- node helpers
def _math(nodes, op, a, b=None, label="") -> bpy.types.ShaderNode:
    n = nodes.new("ShaderNodeMath")
    n.operation = op
    n.label = label or op.lower()
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            v.id_data.links.new(v, n.inputs[i])
    return n


def _band(nodes, state_sock, lo, hi, label) -> bpy.types.NodeSocket:
    """Mask: lo < state < hi."""
    gt = _math(nodes, "GREATER_THAN", state_sock, lo)
    lt = _math(nodes, "LESS_THAN", state_sock, hi)
    m = _math(nodes, "MULTIPLY", gt.outputs[0], lt.outputs[0], label)
    return m.outputs[0]


def shell_material(map_path: Path) -> bpy.types.Material:
    mat = bpy.data.materials.new("shell_far")
    mat.use_nodes = True
    mat.surface_render_method = "DITHERED"
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    # equirect UV from object-space direction (contract: sim/statemaps.py)
    geo = nodes.new("ShaderNodeNewGeometry")
    pos = nodes.new("ShaderNodeVectorMath")
    pos.operation = "NORMALIZE"
    links.new(geo.outputs["Position"], pos.inputs[0])
    xyz = nodes.new("ShaderNodeSeparateXYZ")
    links.new(pos.outputs["Vector"], xyz.inputs[0])
    u = _math(
        nodes,
        "ADD",
        _math(
            nodes,
            "DIVIDE",
            _math(nodes, "ARCTAN2", xyz.outputs["Y"], xyz.outputs["X"]).outputs[0],
            2.0 * math.pi,
        ).outputs[0],
        0.5,
        "u",
    )
    v = _math(
        nodes,
        "ADD",
        _math(
            nodes, "DIVIDE", _math(nodes, "ARCSINE", xyz.outputs["Z"]).outputs[0], math.pi
        ).outputs[0],
        0.5,
        "v",
    )
    uv = nodes.new("ShaderNodeCombineXYZ")
    links.new(u.outputs[0], uv.inputs["X"])
    links.new(v.outputs[0], uv.inputs["Y"])

    # statemap SEQUENCE: map k covers frames [(k-1)*24+1, k*24]; a driver on
    # frame_offset steps the displayed map (displayed = scene_frame + offset)
    img = bpy.data.images.load(str(map_path))
    img.source = "SEQUENCE"
    img.colorspace_settings.name = "Non-Color"
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Closest"
    tex.extension = "REPEAT"
    tex.image_user.frame_start = 1
    tex.image_user.frame_duration = N_FRAMES // STATEMAP_EVERY
    tex.image_user.use_auto_refresh = True
    drv = tex.image_user.driver_add("frame_offset").driver
    drv.expression = f"int((frame-1)//{STATEMAP_EVERY})+1-frame"
    links.new(uv.outputs[0], tex.inputs["Vector"])

    rgb = nodes.new("ShaderNodeSeparateColor")
    links.new(tex.outputs["Color"], rgb.inputs[0])
    r, g, b = rgb.outputs

    # sub-cell light texture: cells are ~47 units wide, so per-cell emission
    # reads as glowing hexes; a fine world-space noise breaks lights into
    # streets/specks. streets = noise^4 (sparse bright pockets).
    streets_tex = nodes.new("ShaderNodeTexNoise")
    streets_tex.inputs["Scale"].default_value = 0.05
    streets_tex.inputs["Detail"].default_value = 3.0
    links.new(geo.outputs["Position"], streets_tex.inputs["Vector"])
    streets = _math(nodes, "POWER", streets_tex.outputs["Fac"], 8.0, "streets")

    state = _math(nodes, "MULTIPLY", r, 3.0, "state")
    void_m = _math(nodes, "LESS_THAN", state.outputs[0], 0.5, "void")
    truss_m = _band(nodes, state.outputs[0], 0.5, 1.5, "truss")
    live_m = _math(nodes, "GREATER_THAN", state.outputs[0], 2.5, "live")

    # emission: ember worklights on truss (brighten with progress), city on live
    ember_k = _math(
        nodes,
        "MULTIPLY",
        _math(
            nodes,
            "MULTIPLY",
            truss_m,
            _math(
                nodes, "ADD", _math(nodes, "MULTIPLY", g, 0.7).outputs[0], 0.3, "truss ramp"
            ).outputs[0],
            "ember cell",
        ).outputs[0],
        _math(nodes, "MULTIPLY", streets.outputs[0], 8.0, "work specks").outputs[0],
        "ember",
    )
    city_ramp = nodes.new("ShaderNodeMapRange")
    city_ramp.interpolation_type = "SMOOTHSTEP"
    city_ramp.inputs["From Min"].default_value = 0.55
    city_ramp.inputs["From Max"].default_value = 0.88
    links.new(b, city_ramp.inputs["Value"])
    city_cell = _math(nodes, "MULTIPLY", live_m.outputs[0], city_ramp.outputs[0], "city cell")
    city_k = _math(
        nodes,
        "MULTIPLY",
        city_cell.outputs[0],
        _math(nodes, "MULTIPLY", streets.outputs[0], 20.0, "street gain").outputs[0],
        "city",
    )

    ember_col = nodes.new("ShaderNodeMixRGB")
    ember_col.blend_type = "MULTIPLY"
    ember_col.inputs["Fac"].default_value = 1.0
    ember_col.inputs["Color1"].default_value = EMBER
    links.new(ember_k.outputs[0], ember_col.inputs["Color2"])
    city_col = nodes.new("ShaderNodeMixRGB")
    city_col.blend_type = "MULTIPLY"
    city_col.inputs["Fac"].default_value = 1.0
    city_col.inputs["Color1"].default_value = CITY
    links.new(city_k.outputs[0], city_col.inputs["Color2"])
    # plate cells: sparse pale commissioning lights, ramping with progress
    plate_m = _band(nodes, state.outputs[0], 1.5, 2.5, "plate")
    plate_k = _math(
        nodes,
        "MULTIPLY",
        _math(nodes, "MULTIPLY", plate_m, g, "plate ramp").outputs[0],
        _math(
            nodes,
            "MULTIPLY",
            _math(nodes, "GREATER_THAN", b, 0.9, "plate sparse").outputs[0],
            streets.outputs[0],
            "plate specks",
        ).outputs[0],
        "plate lights",
    )
    plate_col = nodes.new("ShaderNodeMixRGB")
    plate_col.blend_type = "MULTIPLY"
    plate_col.inputs["Fac"].default_value = 1.0
    plate_col.inputs["Color1"].default_value = (0.55, 0.75, 1.0, 1.0)
    links.new(plate_k.outputs[0], plate_col.inputs["Color2"])
    emis_a = nodes.new("ShaderNodeMixRGB")
    emis_a.blend_type = "ADD"
    emis_a.inputs["Fac"].default_value = 1.0
    links.new(ember_col.outputs[0], emis_a.inputs["Color1"])
    links.new(city_col.outputs[0], emis_a.inputs["Color2"])
    emis_out = nodes.new("ShaderNodeMixRGB")
    emis_out.blend_type = "ADD"
    emis_out.inputs["Fac"].default_value = 1.0
    links.new(emis_a.outputs[0], emis_out.inputs["Color1"])
    links.new(plate_col.outputs[0], emis_out.inputs["Color2"])

    # alpha: void 0, truss 0.35 (unplated frame is mostly open — the frontier
    # deck is a lattice over the glowing interior), else 1
    alpha = _math(
        nodes,
        "SUBTRACT",
        _math(nodes, "SUBTRACT", 1.0, void_m.outputs[0]).outputs[0],
        _math(nodes, "MULTIPLY", truss_m, 0.65).outputs[0],
        "alpha",
    )

    # the star's point light physically lights the inner faces (terminator,
    # falloff, spill through the gap); emission is only the decoded surface
    # signage (ember worklights + city lights), visible from both sides.
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.055, 0.05, 0.045, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.6
    rough = _math(nodes, "ADD", _math(nodes, "MULTIPLY", b, 0.3).outputs[0], 0.35, "rough")
    links.new(rough.outputs[0], bsdf.inputs["Roughness"])
    links.new(emis_out.outputs[0], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 2.5
    links.new(alpha.outputs[0], bsdf.inputs["Alpha"])

    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def star_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("star")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = STAR_COLOR
    em.inputs["Strength"].default_value = 40.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return mat


def build_world() -> None:
    world = bpy.data.worlds.new("space")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()
    # pinpoint stars: voronoi F1 distance thresholded to dots, brightness
    # varied per-cell from the voronoi color channel
    coord = nodes.new("ShaderNodeTexCoord")
    vor = nodes.new("ShaderNodeTexVoronoi")
    vor.feature = "F1"
    vor.inputs["Scale"].default_value = 140.0
    vor.inputs["Randomness"].default_value = 1.0
    links.new(coord.outputs["Generated"], vor.inputs["Vector"])
    dots = nodes.new("ShaderNodeMapRange")
    dots.interpolation_type = "SMOOTHSTEP"
    dots.inputs["From Min"].default_value = 0.035
    dots.inputs["From Max"].default_value = 0.012
    links.new(vor.outputs["Distance"], dots.inputs["Value"])
    cell_val = _math(nodes, "POWER", None, 3.0, "brightness variety")
    hsv = nodes.new("ShaderNodeSeparateColor")
    links.new(vor.outputs["Color"], hsv.inputs[0])
    links.new(hsv.outputs[0], cell_val.inputs[0])
    star_i = _math(nodes, "MULTIPLY", dots.outputs["Result"], cell_val.outputs[0], "stars")
    gain = _math(nodes, "MULTIPLY", star_i.outputs[0], 4.0, "star gain")
    bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.85, 0.9, 1.0, 1.0)
    links.new(gain.outputs[0], bg.inputs["Strength"])
    out = nodes.new("ShaderNodeOutputWorld")
    links.new(bg.outputs[0], out.inputs["Surface"])


def add_sphere(name: str, radius: float, mat: bpy.types.Material, segments=256) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=segments // 2, radius=radius)
    ob = bpy.context.active_object
    ob.name = name
    bpy.ops.object.shade_smooth()
    ob.data.materials.append(mat)
    return ob


def add_star_light() -> None:
    light = bpy.data.lights.new("star_light", type="POINT")
    light.energy = 1e10
    light.color = STAR_COLOR[:3]
    light.shadow_soft_size = STAR_R
    ob = bpy.data.objects.new("star_light", light)
    bpy.context.collection.objects.link(ob)


def look_at(ob: bpy.types.Object, target: Vector, up_hint: Vector | None = None) -> None:
    """Aim -Z at target with an explicit up hint (default: radial, i.e. away
    from the shell center — to_track_quat would roll the camera toward world
    +Z, which is sideways for most points on a sphere)."""
    f = (target - ob.location).normalized()
    up = (up_hint or ob.location).normalized()
    r = f.cross(up)
    if r.length < 1e-6:
        r = f.cross(Vector((1.0, 0.0, 0.0)))
    r.normalize()
    u = r.cross(f)
    ob.rotation_euler = Matrix((r, u, -f)).transposed().to_euler()


def add_camera(pos: Vector, target: Vector, lens=32.0, ship_light=False) -> bpy.types.Object:
    cam = bpy.data.cameras.new("cam")
    cam.lens = lens
    cam.clip_start = 0.5
    cam.clip_end = 30000.0
    ob = bpy.data.objects.new("cam", cam)
    bpy.context.collection.objects.link(ob)
    ob.location = pos
    look_at(ob, target)
    bpy.context.scene.camera = ob
    if ship_light:
        # the freighter's floodlight: diegetic light source for night flyovers,
        # parented to the camera so the deck below is always readable
        light = bpy.data.lights.new("ship_light", type="POINT")
        light.energy = 1.5e5
        light.color = (1.0, 0.85, 0.65)
        light.shadow_soft_size = 2.0
        lob = bpy.data.objects.new("ship_light", light)
        bpy.context.collection.objects.link(lob)
        lob.parent = ob
        lob.location = (0.0, -2.0, 2.0)  # slightly behind/above the lens
    return ob


def _bulk_keys(ob: bpy.types.Object, data_path: str, count: int, values: np.ndarray) -> None:
    """Per-frame keyframes via the 5.x slotted-action API (action.fcurves is gone)."""
    ad = ob.animation_data or ob.animation_data_create()
    if ad.action is None:
        act = bpy.data.actions.new(f"{ob.name}_act")
        ad.action = act
        slot = act.slots.new(id_type="OBJECT", name=ob.name)
        ad.action_slot = slot
        layer = act.layers.new("base")
        layer.strips.new(type="KEYFRAME")
    act = ad.action
    bag = act.layers[0].strips[0].channelbag(ad.action_slot, ensure=True)
    n = len(values)
    co = np.empty((n, 2))
    co[:, 0] = np.arange(1, n + 1)
    for i in range(count):
        fc = bag.fcurves.new(data_path=data_path, index=i)
        fc.keyframe_points.add(n)
        co[:, 1] = values[:, i]
        fc.keyframe_points.foreach_set("co", co.ravel())
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
        fc.update()


def build_ship_rig() -> bpy.types.Object:
    """The freighter: an empty animated from path.npz, camera + cockpit window
    parented to it. Ship orientation IS the camera convention (-Z fwd, +Y up)."""
    path = np.load(DATA / "path.npz")
    ship = bpy.data.objects.new("ship", None)
    bpy.context.collection.objects.link(ship)
    ship.rotation_mode = "QUATERNION"
    _bulk_keys(ship, "location", 3, path["pos"].astype(np.float64))
    _bulk_keys(ship, "rotation_quaternion", 4, path["quat"].astype(np.float64))

    cam = bpy.data.cameras.new("cam")
    cam.lens = 26.0
    cam.clip_start = 0.1
    cam.clip_end = 30000.0
    cob = bpy.data.objects.new("cam", cam)
    bpy.context.collection.objects.link(cob)
    cob.parent = ship
    bpy.context.scene.camera = cob

    build_cockpit(ship)

    # landing floodlight: a SPOT (points radiate backward onto the mullions)
    light = bpy.data.lights.new("ship_light", type="SPOT")
    light.energy = 2.5e5
    light.color = (1.0, 0.85, 0.65)
    light.shadow_soft_size = 2.0
    light.spot_size = 2.4
    light.spot_blend = 0.6
    lob = bpy.data.objects.new("ship_light", light)
    bpy.context.collection.objects.link(lob)
    lob.parent = ship
    lob.location = (0.0, -0.8, -4.0)  # outside the hull, ahead of the glass
    lob.rotation_euler = (-0.30, 0.0, 0.0)  # pitched down at the deck
    return ship


def build_cockpit(ship: bpy.types.Object) -> None:
    """Window mullions + console silhouette in camera space (z=-0.9 plane)."""
    dark = bpy.data.materials.new("cockpit_dark")
    dark.use_nodes = True
    b = dark.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.008, 0.008, 0.01, 1.0)
    b.inputs["Roughness"].default_value = 0.9
    glow = bpy.data.materials.new("console_glow")
    glow.use_nodes = True
    g = glow.node_tree.nodes["Principled BSDF"]
    g.inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1.0)
    g.inputs["Emission Color"].default_value = (1.0, 0.55, 0.25, 1.0)
    g.inputs["Emission Strength"].default_value = 1.2

    verts: list[list[float]] = []
    faces: list[list[int]] = []

    def box(cx, cy, cz, hx, hy, hz):
        i = len(verts)
        for dz in (-hz, hz):
            for dy in (-hy, hy):
                for dx in (-hx, hx):
                    verts.append([cx + dx, cy + dy, cz + dz])
        faces.extend(
            [
                [i, i + 1, i + 3, i + 2],
                [i + 4, i + 6, i + 7, i + 5],
                [i, i + 2, i + 6, i + 4],
                [i + 1, i + 5, i + 7, i + 3],
                [i, i + 4, i + 5, i + 1],
                [i + 2, i + 3, i + 7, i + 6],
            ]
        )

    w, h, z, t = 0.60, 0.36, -0.9, 0.05  # window half-extents, plane, beam size
    box(0, h + t / 2, z, w + t, t / 2, t)  # top
    box(0, -h - t / 2, z, w + t, t / 2, t)  # bottom
    box(-w - t / 2, 0, z, t / 2, h + t, t)  # left
    box(w + t / 2, 0, z, t / 2, h + t, t)  # right
    box(0.19, 0, z, 0.012, h, t * 0.7)  # off-center mullion
    mesh = bpy.data.meshes.new("window_frame")
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(dark)
    ob = bpy.data.objects.new("window_frame", mesh)
    ob.parent = ship
    bpy.context.collection.objects.link(ob)

    verts2: list[list[float]] = []
    faces2: list[list[int]] = []
    i = len(verts2)
    # console: angled slab under the window (from window sill toward viewer)
    for y, zz in ((-h - t, z), (-h - 0.30, z + 0.42)):
        verts2.extend([[-w - t, y, zz], [w + t, y, zz]])
    faces2.append([i, i + 1, i + 3, i + 2])
    mesh2 = bpy.data.meshes.new("console")
    mesh2.from_pydata(verts2, [], faces2)
    mesh2.materials.append(dark)
    ob2 = bpy.data.objects.new("console", mesh2)
    ob2.parent = ship
    bpy.context.collection.objects.link(ob2)

    # indicator strip on the console lip (dim warm interior presence)
    verts3: list[list[float]] = []
    faces3: list[list[int]] = []

    def box3(cx, cy, cz, hx, hy, hz):
        i = len(verts3)
        for dz in (-hz, hz):
            for dy in (-hy, hy):
                for dx in (-hx, hx):
                    verts3.append([cx + dx, cy + dy, cz + dz])
        faces3.extend(
            [
                [i, i + 1, i + 3, i + 2],
                [i + 4, i + 6, i + 7, i + 5],
                [i, i + 2, i + 6, i + 4],
                [i + 1, i + 5, i + 7, i + 3],
                [i, i + 4, i + 5, i + 1],
                [i + 2, i + 3, i + 7, i + 6],
            ]
        )

    for k in range(7):
        box3(-0.4 + k * 0.13, -h - 0.24, z + 0.36, 0.02, 0.008, 0.004)
    mesh3 = bpy.data.meshes.new("console_lights")
    mesh3.from_pydata(verts3, [], faces3)
    mesh3.materials.append(glow)
    ob3 = bpy.data.objects.new("console_lights", mesh3)
    ob3.parent = ship
    bpy.context.collection.objects.link(ob3)

    # instrument glow: a tiny warm light at the console so the mullions read
    inst = bpy.data.lights.new("instrument_glow", type="POINT")
    inst.energy = 6.0
    inst.color = (1.0, 0.55, 0.28)
    inst.shadow_soft_size = 0.3
    iob = bpy.data.objects.new("instrument_glow", inst)
    bpy.context.collection.objects.link(iob)
    iob.parent = ship
    iob.location = (0.0, -0.40, -0.55)


def build_compositor() -> None:
    """Bloom via the 5.x group-based compositor (glare options are sockets now)."""
    sc = bpy.context.scene
    ng = bpy.data.node_groups.new("sunforge_comp", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    # NB: the group INPUT socket is not auto-fed the render (renders white);
    # pull the pass from a Render Layers node inside the group instead.
    rl = ng.nodes.new("CompositorNodeRLayers")
    gout = ng.nodes.new("NodeGroupOutput")
    glare = ng.nodes.new("CompositorNodeGlare")
    glare.inputs["Type"].default_value = "Bloom"
    glare.inputs["Threshold"].default_value = 1.5
    glare.inputs["Strength"].default_value = 0.35
    glare.inputs["Size"].default_value = 0.8
    ng.links.new(rl.outputs["Image"], glare.inputs["Image"])
    ng.links.new(glare.outputs["Image"], gout.inputs["Image"])
    sc.compositing_node_group = ng
    sc.render.use_compositing = True


def find_frontiers(frame: int) -> tuple[float, float]:
    """(solid, band) frontier angles from the actual CA state (never eyeball).

    Walk the equator great circle from the far side toward the gap (+X); a
    frontier is where the local done-fraction drops below 0.5. `solid` uses
    plated cells (opaque ground), `band` uses trusses (skeletal frontier).
    """
    lat = np.load(DATA / "lattice.npz")
    ca = np.load(DATA / "ca.npz")
    centers = lat["centers"].astype(np.float64)

    def frontier_of(done: np.ndarray) -> float:
        for theta in np.arange(178.0, 40.0, -1.0):
            t = math.radians(theta)
            p = np.array([math.cos(t), math.sin(t), 0.0])
            near = centers @ p > math.cos(math.radians(6.0))
            if near.any() and float(done[near].mean()) < 0.5:
                return float(theta)
        return 76.0

    solid = frontier_of(ca["t_plate"] <= frame)
    band = frontier_of(ca["t_truss"] <= frame)
    print(f"bsh: solid frontier {solid:.0f}°, truss frontier {band:.0f}°")
    return solid, band


def on_shell(theta_deg: float, around_deg: float, r: float) -> Vector:
    """Point at polar angle theta from the gap axis, spun around_deg about +X."""
    t, a = math.radians(theta_deg), math.radians(around_deg)
    return Vector((math.cos(t), math.sin(t) * math.cos(a), math.sin(t) * math.sin(a))) * r


def stage_camera(shot: str, frame: int) -> tuple[Vector, Vector, float]:
    """(position, target, lens) for a named shot, staged against the sim.

    hero: 350 up, shooting along the band (cities | embers | aperture glow).
    s2:   film altitude over the plated/commissioning corridor, terminator zone.
    s3:   film altitude at the truss frontier itself.
    The corridor arc is the z=0, y>0 equator great circle (sim/flightpath.py).
    """
    solid, band = find_frontiers(frame)
    if shot == "hero":
        cam_theta = (solid + band) / 2.0
        return (
            on_shell(cam_theta, 0.0, SHELL_R + 350.0),
            on_shell(cam_theta - 7.0, 14.0, SHELL_R),
            28.0,
        )
    # film altitude, with clearance over the tallest greebles (towers ~R+21)
    # and a lateral check against corridor foundry spires (45+ tall)
    theta = solid + 12.0 if shot == "s2" else band + 3.0
    alt = 30.0 if shot == "s2" else 10.0
    lat = np.load(DATA / "lattice.npz")
    cor = np.load(DATA / "corridor.npz")
    spires = lat["centers"][np.intersect1d(cor["ids"], lat["pentagons"])].astype(np.float64)

    def clear_of_spires(t: float) -> bool:
        p = np.array(on_shell(t, 0.0, 1.0))
        return not len(spires) or np.degrees(np.arccos(np.clip(spires @ p, -1, 1))).min() > 3.5

    for dt in (0.0, 4.0, -4.0, 8.0):
        if clear_of_spires(theta + dt):
            theta += dt
            break
    cam_pos = on_shell(theta, 0.0, SHELL_R + alt)
    target = on_shell(theta - 2.2, 0.0, SHELL_R + 2.0)
    return cam_pos, target, 30.0


def main() -> None:
    args = parse_args()
    wipe()
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 1, N_FRAMES
    sc.frame_set(args.frame)

    add_sphere("shell_far", SHELL_R, shell_material(first_statemap()))
    add_sphere("star", STAR_R, star_material(), segments=64)
    add_star_light()
    build_world()

    n = build_near_layer(DATA, args.frame, seed=args.seed)
    print(f"bsh: near layer: {n} corridor cells built")

    if args.shot == "film":
        build_ship_rig()
    else:
        cam_pos, target, lens = stage_camera(args.shot, args.frame)
        add_camera(cam_pos, target, lens=lens, ship_light=args.shot != "hero")
    sc.view_settings.exposure = 0.0
    sc.eevee.use_raytracing = True  # emissive lamps/ground light nearby geometry
    build_compositor()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out))
    print(f"BSH_OK build -> {args.out}")


if __name__ == "__main__":
    main()
