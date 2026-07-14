"""sunforge stage 3 (Blender-side): render the film, resumably.

Run via:  tools/blender.sh run toys/sunforge/render_anim.py -- --start 1 --end 2880

One Blender process per chunk (per-frame invocation pays ~1.5s startup —
measured, see DESIGN.md §4). Skips frames whose PNG already exists in
renders/frames/, so any chunk can be re-run or resumed after a crash.
"""

# M6. Not yet implemented.

raise NotImplementedError("M6: chunked, skip-existing animation render")
