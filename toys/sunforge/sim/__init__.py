"""sunforge sim — the uv-side machinery (numpy, seeded, no bpy).

Modules emit plain data into renders/data/ for the Blender-side scripts:
lattice (Goldberg polyhedron), construction (the CA), swarm (boids with
jobs), flightpath (camera spline), events (the film's score).
"""

FPS = 24
DURATION_S = 120
N_FRAMES = FPS * DURATION_S  # 2880
SHELL_RADIUS = 2000.0
