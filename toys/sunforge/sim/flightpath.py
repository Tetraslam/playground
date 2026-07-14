"""The freighter's flight path (DESIGN.md §2.5).

Catmull-Rom spline through control points staged against the sim state
(S3 must overfly the CA front's actual f769 isochrone). Arc-length
parameterized easing, banking from curvature, seeded perlin micro-shake,
altitude profile per shot.

Output: renders/data/path.json  per-frame camera/ship transform + shake.
"""

# M4. Not yet implemented.


def build_path(lattice, ca_history, events, seed: int):
    raise NotImplementedError("M4: spline + banking + shake")
