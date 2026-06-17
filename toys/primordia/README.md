# primordia

A coevolutionary ecosystem where **behavior is evolved, not authored**.

Prey eat plants. Predators eat prey. Every critter's actions — foraging, fleeing,
hunting, crowding — are driven by a small feedforward neural net whose **weights
are its genome**. Offspring inherit a mutated copy. No behavior is hand-coded;
everything you see is selection pressure on the weights.

This is a tier-3 toy per AGENTS.md: a system with state and evolution that runs
and surprises. Not a picture of a system — the system itself.

## what emerges

Across seeds (1, 3, 12, 42), you reliably get:

- **Lotka-Volterra-style oscillations** — prey boom, predators boom lagging behind,
  prey crash, predators starve, plants recover, repeat. No equation for this is
  in the code; it falls out of the predation + reproduction rules.
- **Predator busts** — predators overshoot, wipe local prey, then starve down to
  a fraction of their peak (e.g. 150 → 52). This is the selection event: only
  predators that learned to hunt efficiently survive the bust.
- **Stable coexistence** over 3000+ steps with no extinctions, no cap-pegging.

The brains start random (N(0, 0.6) weights). Whether they *improve* over
evolutionary time is something you can measure — the toy logs births/deaths per
species. A run with `mut=0.0` (frozen genomes) is the null hypothesis.

## how to run

```bash
# live terminal sim (ASCII grid + stats), perturbable mid-flight
uv run python toys/primordia/main.py

# headless, just see the trajectory
uv run python toys/primordia/main.py --steps 3000 --no-tty --seed 1

# save PNG frames for a timelapse
uv run python toys/primordia/main.py --steps 2000 --no-tty --seed 1 \
    --save-frames examples/run --frame-every 400
```

### live controls (tty mode)

| key | action |
|-----|--------|
| `f` | burst of food (refill all plant cells) |
| `p` | spawn 10 predators (mutated from population mean genome) |
| `P` | spawn 20 prey |
| `m` | cycle mutation rate (low → med → high) |
| `k` | cull half of both populations |
| `+`/`-` | speed up / slow down (steps per render) |
| `q` | quit |

## how it works

**Brain:** 14 inputs → 8 hidden (tanh) → 2 outputs (turn, speed). 138 weights
total = the genome. Inputs are 4 directional quadrants (back/left/front/right)
for three signal types — food, conspecifics, threats — plus own energy and a
bias. Evaluated vectorized across the whole population each step via `einsum`.

**Sensing:** pairwise on a torus, inverse-distance weighted, binned into 4
angular quadrants relative to each critter's heading. O(n·m) but n,m stay under
~400 so it's fast on CPU.

**Selection:** critters die when energy ≤ 0 or age > ~4000 steps. Reproduce
when energy exceeds a threshold; child gets 45% of parent's energy, genome
mutated (15% of weights perturbed with Gaussian noise at the mutation rate).

**Balance** (the hard part — tuned so neither species caps out):
- prey are faster (2.4 vs 1.6) but burn less; they escape if they learn to flee
- predators burn hot (0.095/step) and must nearly touch prey (eat_r 0.8) to kill
- plants are scarce (food_rate 0.02) so idle foragers starve
- a predator bust is the key selection event — only skilled hunters survive

## files

- `main.py` — everything: world, brain, sensing, render (terminal + PNG), live loop
- `examples/run/` — sample frames from a 2000-step run (seed 1)

## dependencies

numpy only. PNG output is pure stdlib (`zlib` + hand-rolled PNG chunks).

## could go deeper

- log mean genome fitness over time, plot the evolutionary signal
- gradient-train a single brain via RL, drop it in, see if it dominates
- spatial memory: let plants grow where prey die (fertilizer), creating clumps
- prey that signal danger to kin (selection on communication)

_Built by glm._
