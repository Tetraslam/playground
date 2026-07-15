# sunforge — design doc

A two-minute continuous shot from the observation window of a freighter on
final approach across a Dyson shell that is *still being built*. The film is
the window; the toy is the machinery behind it: a construction simulation on
a spherical lattice, drone swarms with jobs, a traffic/event timeline, and a
flight path threaded through all of it. Everything on screen is driven by
simulation output, not hand-keyed.

Working titles: the shell is **the Forge**, the freighter is **the ember**
(placeholder — stretch goal is to name star/ship/stations with `toys/qurwen`
so the worldbuilding composes).

## 1. The film (120s @ 24fps = 2880 frames, one unbroken take)

POV is locked inside the cockpit: window mullions, faint glass reflection,
seeded micro-shake from the engines. No cuts; the variety comes from what the
shell is doing as we cross it.

| shot | time | frames | what happens |
|---|---|---|---|
| S1 "dark side" | 0:00–0:15 | 1–360 | Starfield; a black arc eats the stars — the finished hemisphere in silhouette, rim-lit by the hidden star. City-light grids glitter across dark panels; nav strobes blink in rows. |
| S2 "terminator" | 0:15–0:32 | 361–768 | We cross into worklight. Low-altitude parallax over panel plains; radiator fins glowing dull red; towers and trenches slide past below. A drone swarm overtakes us. |
| S3 "the front" | 0:32–0:52 | 769–1248 | The live construction front: skeletal hex trusses, plates snapping in wave-by-wave (the CA advancing, visibly), weld flashes, drone streams shuttling foundry ↔ frontier. |
| S4 "the gap" | 0:52–1:12 | 1249–1728 | The great unfinished aperture. Raw starlight blasts through: volumetric god rays, exposure clamps down, lens flare, a prominence arcing off the star's limb. The shell's inner face is a mirror furnace. |
| S5 "mass driver" | 1:12–1:30 | 1729–2160 | A launch rail along a finished meridian fires cargo pods in rhythm. Pods streak past the window; one tumbles slightly, an escort drone corrects it. |
| S6 "approach" | 1:30–1:50 | 2161–2640 | The dock spire grows from a glint to a structure. Comms lasers link nodes; other ships hold pattern; we bank (the view rolls), decel thrusters strobe warm light across the cockpit. |
| S7 "dock" | 1:50–2:00 | 2641–2880 | Clamps loom, the window slides into bay shadow, interior lights ripple past, black on contact. Title frame: *sunforge*. |

The camera path is planned *against the sim*: S3 is over whatever isochrone
the CA front actually reaches by f769, so re-seeding the sim re-stages the film.

## 2. The systems (the toy is the system, not the picture)

### 2.1 Shell lattice (`sim/lattice.py`)
Goldberg polyhedron: subdivide an icosahedron (frequency ~48–64), take the
dual → ~23k–41k hex cells (+12 pentagons, which become foundry sites — the
defects are the factories). Per cell: center, orientation frame, area,
adjacency. Pure numpy, seeded, saved to `renders/data/lattice.npz`.

### 2.2 Construction CA (`sim/construction.py`)
Per-cell state machine: `VOID → TRUSS → PLATE → LIVE` (powered, lit).
Growth spreads along adjacency from the 12 foundries with:
- per-edge noise (ragged, organic fronts — no clean circles),
- a supply budget coupled to drone throughput (build rate rises where swarms are),
- occasional stalls/bursts (events: a foundry goes down for 10s, front pauses).

Runs 2880 ticks (1 tick = 1 frame). Two outputs:
- **far field:** equirect "state maps" (PNG, 4096×2048) every 24 frames →
  Blender image-sequence texture driving emission/albedo of the whole-sphere
  mesh. 120 images ≈ the entire animation of a 40k-cell process, for free.
- **near field:** `ca.npz` stores per-cell stage-entry times in film frames
  (the whole history, compactly); M4 extracts the flight-corridor subset for
  real geometry pop-in + weld-flash lights.

### 2.3 Drone swarms (`sim/swarm.py`)
Boids (separation/alignment/cohesion + goal-seek) with *jobs*: pick up at a
foundry spire, deliver to a sampled cell on the active front, repeat. ~300
near-corridor drones baked to per-frame positions/headings (`drones.npz`).
Distant swarms are cheap emissive particles. Drone throughput feeds back into
CA build rate (2.2), so the swarm you watch is the reason the front moves.

### 2.4 Traffic & events (`sim/events.py` → `events.json`)
Declarative timeline consumed by both sim and Blender: pod launches (ballistic
arcs from the rail, staggered), the S4 prominence, comms-laser on/off pairs,
pattern traffic (3–5 ships on own splines), dock strobe sequences, exposure
track, shake amplitude track. One JSON file = the film's score.

### 2.5 Flight path (`sim/flightpath.py`)
Catmull-Rom spline through hand-picked control points (chosen against the sim
state), arc-length parameterized with easing; roll from path curvature
(banking); seeded perlin micro-shake; altitude profile (high over the dark
side, low over the front, threading the gap edge). Emits `path.json`
(per-frame camera transform) — Blender applies it, no IK/physics needed.

### 2.6 The star
Emissive sphere + thin volumetric shell for limb glow; one animated
prominence (curve + taper, noise-displaced) cued at f1250. Only directly
visible in S4 and through gaps — scarcity keeps it special.

## 3. Scale strategy (the big cheat)

A real shell is 1 AU; you cannot have curvature and rivets in one honest
scale. Cinematic scale instead: shell radius **R = 2000 units**, flight
altitude 4–8, ship ~0.1. Two detail layers welded at the corridor boundary:

- **far layer:** one sphere mesh, state-map image sequence (2.2) drives
  emission (city grids, worklights) + roughness. Cheap, animates the whole
  planet-scale process.
- **near layer:** only cells within ~30 units of the flight path (precomputed
  from `path.json`; ~3–5% of cells) get instanced geometry: truss variant,
  plate variant, LIVE variant with greebles. Visibility keyframed from CA
  events. Beyond the corridor the far layer takes over; the seam hides under
  parallax and haze.

### Greeble kit (`build_scene.py`)
~8 code-built modules, 100–500 tris each, instanced with seeded variation:
radiator fin, comms tower, dish cluster, trench segment, city-block cluster,
crane, foundry spire, dock clamp. All emission-textured (EEVEE-cheap).

## 4. Render plan

- **Engine:** EEVEE (Blender 5 EEVEE-Next) @ 1920×1080 for the film; Cycles
  /OPTIX @ 256 for hero stills only.
- **Probe timings (RTX 5070 Ti laptop, trivial scene — floors, not
  estimates):** EEVEE 1080p ≈ 1.7s wall (~1.5s is process startup!), Cycles
  128spp 1080p ≈ 5s. Consequence: the film renders in **one Blender process**
  (`render_anim.py`: opens the .blend, renders a frame range, skips existing
  PNGs → resumable, chunkable). Never per-frame `blender.sh render` calls.
- **Budget:** real scene target ≤ 5s/frame EEVEE → 2880 frames ≈ **4h**.
  Guardrail per AGENTS.md: preview single frames from each shot *before* any
  long batch; full-film preview pass (960×540, every 4th frame) before the
  final 1080p run.
- **Compositor:** glare (bloom + streaks for S4), vignette + slight chromatic
  aberration at window edges, animated exposure from events.json.
- **Audio (stretch):** procedural bed on the uv side (numpy → wav: engine hum,
  radio chirps, pod whooshes, the dock thunk — all cued from events.json),
  muxed by ffmpeg at encode time.
- **Deliverables:** `renders/film.mp4` (full 2 min, local); `examples/` gets
  6–10 hero stills, 3–5s webp excerpts of S1/S3/S4/S5/S7, and a full-film
  filmstrip. The mp4 is committable only if < 20 MB (hook); otherwise excerpts
  carry the README.

## 5. Pipeline & data contract

```
uv side (sunforge pkg, seeded, deterministic):
  gen_scene.py --seed 7
    -> renders/data/lattice.npz        cells, frames, adjacency
    -> renders/data/ca.npz             per-cell stage-entry times (film frames)
    -> renders/data/statemap_####.png  equirect far-field emission sequence
    -> renders/data/drones.npz         per-frame near-drone transforms
    -> renders/data/path.npz           per-frame ship transform (pos + quat)
    -> renders/data/events.json        the score (pods, lasers, flare, exposure)
    -> renders/data/ambient.wav        (stretch) procedural soundtrack

blender side (bpy + bundled numpy + stdlib ONLY):
  build_scene.py    data -> renders/shell.blend (everything, keyframed)
  render_anim.py    shell.blend + frame range -> renders/frames/f_####.png
                    (skip-existing => resumable; run in chunks)

encode:
  ffmpeg frames+wav -> renders/film.mp4; tools/blender.sh encode for excerpts
```

Determinism: one `--seed` threads through lattice noise, CA noise, boids
init, shake, greeble variation. Same seed → same film, bit for bit.

## 6. Milestones

- **M1 — the sim runs headless.** Lattice + CA + statemap PNGs; review the
  front advancing as images. No Blender.
- **M2 — the far layer lives.** Sphere + statemap sequence + star + space
  HDRI in Blender; hero still of the terminator from orbit height.
- **M3 — the near layer.** Corridor extraction, greeble kit, instancing,
  CA-driven pop-in; flyover stills for S2/S3.
- **M4 — the ship flies.** path.json → camera rig + cockpit window frame +
  shake + banking; 5s S2 test loop at preview res (filmstrip review).
- **M5 — everything happens.** Drones, pods, lasers, prominence, exposure
  track; per-shot preview filmstrips, timing tuned against the table in §1.
- **M6 — the film.** Full preview pass review → final 1080p EEVEE run
  (chunked, resumable, overnight) → encode + audio mux.
- **M7 — ship it.** Hero stills (Cycles), excerpts, README with embedded
  media, qurwen names, FEEDBACK notes on what broke.

## 7. Risks / open questions

- **EEVEE frame-time blowup** near the corridor (instances + volumetrics).
  Mitigation: instance budget per shot, volumetrics only in S4, haze via
  world shader elsewhere.
- **Statemap texel density** at low altitude — 4096×2048 equirect ≈ 3 units/px
  at R=2000. Fine for far field; corridor is real geometry anyway. If seams
  show, bump to 8192 or use per-face UV islands.
- **Keyframe volume**: corridor-only events keep it to low thousands of
  fcurves — fine. Never keyframe all 40k cells.
- **Blender 5 API drift** (EEVEE-Next settings, compositor glare node names):
  verify against this build in M2, not from memory.
- **2-min mp4 > 20 MB**: likely at 1080p. Plan: excerpts in git, full film
  stays local (or a heavily-compressed 720p cut if it squeaks under).

_Built by fable._
