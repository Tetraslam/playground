# saturn

A from-scratch **CDCL SAT solver**. No solver library, no SAT context — just the
algorithm: watched literals, unit propagation with a persistent trail head,
1-UIP conflict analysis, clause learning, VSIDS branching with exponential
decay, and Luby-sequence restarts.

The toy is the solver. The views are a live search trace and a 3-SAT
phase-transition sweep.

## why this exists

Everything else in the playground is a visualizer, an agent sim, a market, a
planner, or worldbuilding. saturn is none of those — it's a foundational search
algorithm, built honestly, that you can watch think. The interesting behavior
isn't drawn on: it's the **3-SAT phase transition** (instances go from trivially
SAT to trivially UNSAT across a razor's edge near α ≈ 4.27 clauses/variable, and
that edge is where search explodes) and the **clause-learning loop** (each
conflict carves a permanent cut out of the search space).

## how to run

```bash
# solve a DIMACS CNF instance
uv run python toys/saturn/main.py solve examples/pt-25.cnf
uv run python toys/saturn/main.py solve examples/pt-25.cnf --trace   # live decisions/conflicts

# generate a random 3-SAT instance at a given clause/variable ratio
uv run python toys/saturn/main.py gen --vars 30 --ratio 4.3 --seed 7 > out.cnf

# sweep the phase transition: random 3-SAT across ratios, with an ASCII hardness chart
uv run python toys/saturn/main.py sweep --vars 40 --samples 30
```

`solve` exits 0 on SAT, 10 on UNSAT (SAT-competition convention) and prints a
validating model on SAT.

## what's in the box

- `saturn.py` — the solver. Watched literals, 1-UIP learning, VSIDS, Luby
  restarts. ~350 lines, no deps.
- `main.py` — CLI: `solve` (DIMACS, optional `--trace`), `gen`, `sweep`.
- `examples/` — a phase-transition instance (`pt-25.cnf`), its solve + trace,
  and a sweep chart (`sweep-vars40.txt`) showing the transition at α ≈ 4.5.

## the phase transition

```
 ratio  sat%    decisions    conflicts   time(ms)  bar
  2.00  100%           21            0        0.2  ########################
  4.00   90%           25           14        0.9  ############################
  4.25   73%           32           21        1.4  ####################################
  4.50   40%           35           29        1.3  ########################################  <- hard
  4.75   23%           34           29        0.8  ######################################
  6.00    0%           24           22        0.6  ###########################
```

Below α ≈ 4 there's so much freedom the first greedy assignment works. Above
α ≈ 5 the clauses overconstrain so hard that conflicts prune everything fast.
The spike — where decisions and conflicts peak and SAT/UNSAT flips — sits right
at the theoretical crossover α ≈ 4.27. saturn finds it empirically.

## correctness

Verified against the pigeonhole principle (PHP, the canonical UNSAT family:
`n` pigeons in `n-1` holes is UNSAT, `n` in `n` is SAT) up to PHP(6,5), and on
200 random 3-SAT instances where every SAT model is checked against its clauses.
UNSAT verdicts hold by construction (CDCL is sound: it only returns UNSAT after
a level-0 conflict).

_Built by glm._
