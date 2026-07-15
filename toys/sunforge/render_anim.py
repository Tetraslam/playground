"""sunforge stage 3 (Blender-side): render the film, resumably.

Run via:
  tools/blender.sh run toys/sunforge/render_anim.py toys/sunforge/renders/shell.blend \
      -- --start 1 --end 2880 [--step 1] [--res 1920x1080] [--samples 64] [--outdir DIR]

ONE Blender process per chunk (a per-frame `blender.sh render` pays ~1.5s
startup each — measured; see DESIGN.md §4). Frames whose PNG already exists
are skipped, so any chunk can be re-run or resumed after a crash.
"""

import argparse
import sys
import time
from pathlib import Path

import bpy

TOY = Path(__file__).parent


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--outdir", type=Path, default=TOY / "renders" / "frames")
    args = ap.parse_args(argv)

    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    w, h = (int(v) for v in args.res.split("x"))
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    sc.eevee.taa_render_samples = args.samples
    sc.render.image_settings.file_format = "PNG"
    args.outdir.mkdir(parents=True, exist_ok=True)

    frames = [f for f in range(args.start, args.end + 1, args.step)]
    todo = [f for f in frames if not (args.outdir / f"f_{f:04d}.png").exists()]
    print(f"bsh: rendering {len(todo)}/{len(frames)} frames -> {args.outdir}")
    t0 = time.perf_counter()
    for i, f in enumerate(todo):
        sc.frame_set(f)
        sc.render.filepath = str(args.outdir / f"f_{f:04d}.png")
        bpy.ops.render.render(write_still=True)
        if i % 20 == 0:
            rate = (time.perf_counter() - t0) / (i + 1)
            print(
                f"bsh: {i + 1}/{len(todo)} ({rate:.1f}s/frame, ~{rate * (len(todo) - i) / 60:.0f}min left)"
            )
    print(f"BSH_OK anim -> {args.outdir} ({len(todo)} rendered, {time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()
