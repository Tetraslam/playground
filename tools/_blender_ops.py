# _blender_ops.py — runs INSIDE Blender, invoked by tools/blender.sh.
# Dispatches on the BSH_CMD env var; all parameters arrive as BSH_* env vars
# (env vars sidestep the bash->blender argv quoting mess).
#
# Not a uv-workspace script. Blender's bundled Python executes this.

import math
import os

import bpy


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def setup_gpu_cycles(samples: int) -> None:
    """Cycles on OPTIX if the GPU is visible, CPU fallback otherwise."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "OPTIX"
        prefs.get_devices()
        n = 0
        for d in prefs.devices:
            d.use = d.type == "OPTIX"
            n += int(d.use)
        if n:
            scene.cycles.device = "GPU"
            print(f"bsh: cycles on OPTIX ({n} device)")
    except Exception as e:  # noqa: BLE001 — playground; CPU render still works
        print(f"bsh: GPU setup failed, CPU fallback: {e}")


def setup_engine() -> None:
    scene = bpy.context.scene
    engine = env("BSH_ENGINE", "eevee")
    if engine == "cycles":
        setup_gpu_cycles(int(env("BSH_SAMPLES", "64")))
    else:
        scene.render.engine = "BLENDER_EEVEE"
    rx, ry = env("BSH_RES", "960x540").split("x")
    scene.render.resolution_x = int(rx)
    scene.render.resolution_y = int(ry)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"


def scene_bbox():
    from mathutils import Vector

    mn = Vector((1e18, 1e18, 1e18))
    mx = Vector((-1e18, -1e18, -1e18))
    found = False
    for ob in bpy.context.scene.objects:
        if ob.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"} and not ob.hide_render:
            for corner in ob.bound_box:
                w = ob.matrix_world @ Vector(corner)
                mn = Vector(map(min, mn, w))
                mx = Vector(map(max, mx, w))
                found = True
    if not found:
        mn, mx = Vector((-1, -1, -1)), Vector((1, 1, 1))
    return mn, mx


def ensure_light() -> None:
    if any(ob.type == "LIGHT" for ob in bpy.context.scene.objects):
        return
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 10))
    sun = bpy.context.object
    sun.data.energy = 3.0
    sun.rotation_euler = (0.6, 0.2, 0.5)
    print("bsh: no light in scene, added a sun")


def ensure_camera() -> None:
    """If the scene has no camera, aim one at the scene bounding box."""
    if bpy.context.scene.camera:
        return
    mn, mx = scene_bbox()
    center = (mn + mx) / 2
    radius = max((mx - mn).length / 2, 0.001)
    cam_data = bpy.data.cameras.new("bsh_cam")
    cam = bpy.data.objects.new("bsh_cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    dist = radius * 2.4
    cam.location = (center.x + dist, center.y - dist, center.z + dist * 0.8)
    track = cam.constraints.new("TRACK_TO")
    pivot = bpy.data.objects.new("bsh_cam_target", None)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.location = center
    track.target = pivot
    bpy.context.scene.camera = cam
    print("bsh: no camera in scene, added one aimed at the bbox")


def cmd_render() -> None:
    setup_engine()
    ensure_camera()
    ensure_light()
    scene = bpy.context.scene
    out = os.path.abspath(env("BSH_OUT"))
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print(f"BSH_OK render -> {out}")


def cmd_turntable() -> None:
    setup_engine()
    ensure_light()
    scene = bpy.context.scene
    frames = int(env("BSH_FRAMES", "96"))

    mn, mx = scene_bbox()
    center = (mn + mx) / 2
    radius = max((mx - mn).length / 2, 0.001)

    pivot = bpy.data.objects.new("bsh_pivot", None)
    scene.collection.objects.link(pivot)
    pivot.location = center

    cam_data = bpy.data.cameras.new("bsh_ttcam")
    cam = bpy.data.objects.new("bsh_ttcam", cam_data)
    scene.collection.objects.link(cam)
    cam.parent = pivot  # parented: orbits when the pivot spins
    dist = radius * 2.4
    cam.location = (dist, -dist, dist * 0.8)  # pivot-local
    track = cam.constraints.new("TRACK_TO")
    track.target = pivot
    scene.camera = cam

    # full 360 across frames+1 with LINEAR interp -> frame N+1 == frame 1,
    # so rendering 1..N gives a seamless loop. (Set the interpolation via the
    # preference: Blender 5's slotted actions dropped legacy action.fcurves.)
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    pivot.rotation_euler = (0, 0, 0)
    pivot.keyframe_insert("rotation_euler", frame=1)
    pivot.rotation_euler = (0, 0, math.tau)
    pivot.keyframe_insert("rotation_euler", frame=frames + 1)

    scene.frame_start, scene.frame_end = 1, frames
    out_dir = os.path.abspath(env("BSH_OUT"))
    os.makedirs(out_dir, exist_ok=True)
    scene.render.filepath = os.path.join(out_dir, "f_")
    bpy.ops.render.render(animation=True)
    print(f"BSH_OK turntable -> {out_dir} ({frames} frames)")


def cmd_new() -> None:
    if env("BSH_EMPTY") == "1":
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
    out = os.path.abspath(env("BSH_OUT"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"BSH_OK new -> {out}")


COMMANDS = {
    "render": cmd_render,
    "turntable": cmd_turntable,
    "new": cmd_new,
}

COMMANDS[os.environ["BSH_CMD"]]()
