"""The film's score (DESIGN.md §2.4): one events.json both sides consume.

Pod launches (ballistic arcs off the mass-driver rail), the S4 prominence,
comms-laser pairs, pattern traffic splines, dock strobes, exposure track,
shake-amplitude track. Shot boundaries per the DESIGN.md §1 table.

Output: renders/data/events.json
"""

SHOTS = {  # frame ranges, inclusive (24 fps)
    "S1_dark_side": (1, 360),
    "S2_terminator": (361, 768),
    "S3_front": (769, 1248),
    "S4_gap": (1249, 1728),
    "S5_mass_driver": (1729, 2160),
    "S6_approach": (2161, 2640),
    "S7_dock": (2641, 2880),
}

# M5. Not yet implemented.


def build_events(lattice, ca_history, path, seed: int):
    raise NotImplementedError("M5: the score")
