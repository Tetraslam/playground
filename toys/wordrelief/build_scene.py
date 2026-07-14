# build_scene.py — stage 2 of wordrelief (runs INSIDE Blender, not uv).
#
# Reads the terrain JSON from gen_terrain.py, builds a vertex-colored relief
# mesh + water plane + sun + sky, and saves a .blend into renders/.
#
# Run:  tools/blender.sh run toys/wordrelief/build_scene.py -- --json toys/wordrelief/renders/vrakh.json

import argparse
import json
import math
import os
import sys

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="terrain JSON from gen_terrain.py")
    ap.add_argument("--out", default="", help="output .blend (default: <json dir>/<word>.blend)")
    ap.add_argument("--height", type=float, default=0.55, help="peak height (terrain spans 2x2)")
    return ap.parse_args(argv)


def srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def clear_scene() -> None:
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)


def build_terrain(data: dict, height: float) -> bpy.types.Object:
    res = data["res"]
    heights = data["heights"]
    colors = data["colors"]

    verts = []
    for y in range(res):
        for x in range(res):
            vx = x / (res - 1) * 2.0 - 1.0
            vy = y / (res - 1) * 2.0 - 1.0
            verts.append((vx, vy, heights[y * res + x] * height))

    faces = []
    for y in range(res - 1):
        for x in range(res - 1):
            i = y * res + x
            faces.append((i, i + 1, i + res + 1, i + res))

    mesh = bpy.data.meshes.new("terrain")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    col = mesh.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
    for i, (r, g, b) in enumerate(colors):
        col.data[i].color = (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), 1.0)

    for p in mesh.polygons:
        p.use_smooth = True

    mat = bpy.data.materials.new("terrain")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    attr = mat.node_tree.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Col"
    mat.node_tree.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.95
    mesh.materials.append(mat)

    ob = bpy.data.objects.new("terrain", mesh)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def build_water(data: dict, height: float) -> None:
    sea_z = data["sea"] * height
    mesh = bpy.data.meshes.new("water")
    s = 1.001  # hair over the terrain to avoid edge z-fighting
    mesh.from_pydata(
        [(-s, -s, sea_z), (s, -s, sea_z), (s, s, sea_z), (-s, s, sea_z)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()

    mat = bpy.data.materials.new("water")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.05, 0.18, 0.30, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.05
    bsdf.inputs["Alpha"].default_value = 0.82
    try:
        mat.surface_render_method = "BLENDED"  # EEVEE transparency
    except AttributeError:
        pass
    mesh.materials.append(mat)

    ob = bpy.data.objects.new("water", mesh)
    bpy.context.scene.collection.objects.link(ob)


def build_light_and_sky(data: dict) -> None:
    sun_data = bpy.data.lights.new("sun", type="SUN")
    sun_data.energy = 4.0
    sun_data.angle = 0.15
    sun = bpy.data.objects.new("sun", sun_data)
    bpy.context.scene.collection.objects.link(sun)
    # low NW light so the relief reads (same direction phonoscape hillshades)
    sun.rotation_euler = (math.radians(55), 0, math.radians(135))

    world = bpy.data.worlds.new("sky")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    # tint the sky by biome temperature: cold words get a paler, colder sky
    t = data["terrain"]["temperature"]
    bg.inputs["Color"].default_value = (0.03 + 0.05 * t, 0.05 + 0.03 * t, 0.09, 1.0)
    bg.inputs["Strength"].default_value = 0.6
    bpy.context.scene.world = world


def main() -> None:
    args = parse_args()
    data = json.loads(open(args.json).read())

    out = args.out or os.path.join(os.path.dirname(args.json), data["word"] + ".blend")

    clear_scene()
    build_terrain(data, args.height)
    build_water(data, args.height)
    build_light_and_sky(data)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
    print(f"wordrelief: {data['word']} ({data['biome']}) -> {out}")


main()
