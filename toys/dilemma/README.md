# dilemma

An **iterated Prisoner's Dilemma** tournament runner. Classic strategies fight it
out round-robin style; you get a leaderboard and a per-pair score matrix.

_Built by kimi._

```bash
# list all built-in strategies
uv run python -m toys.dilemma.dilemma --list

# run the default tournament
uv run python toys/dilemma/main.py

# toy tournament: noisy, short, three strategies
uv run python toys/dilemma/main.py -s tft,all_d,pavlov -r 50 -n 3 --noise 0.02

# write results to csv
uv run python toys/dilemma/main.py --out examples/output.csv
```

## Built-in strategies

| name | behavior |
|---|---|
| `tft` | **Tit-for-Tat**: cooperate, then mirror the opponent's last move |
| `suspicious_tft` | Tit-for-Tat but defects on the first move |
| `all_c` | always cooperate |
| `all_d` | always defect |
| `grudger` | cooperate until the first defection, then defect forever |
| `joss` | mostly Tit-for-Tat, but randomly defects 10% of the time |
| `tester` | defects once, then plays TFT if punished; keeps defecting if not |
| `soft_majo` | cooperate if opponent has cooperated at least as often as defected |
| `pavlov` | win-stay, lose-shift |
| `random` | 50/50 coin flips |

## Scoring

| outcome | A / B |
|---|---|
| both cooperate | 3 / 3 |
| A defects, B cooperates | 5 / 0 |
| A cooperates, B defects | 0 / 5 |
| both defect | 1 / 1 |

A tournament runs every pairing for `--rounds` moves, repeated `--reps` times,
with an optional `--noise` chance that any move is flipped. Strategies are
statefully reinstantiated per match, so randomness is independent.

## Example output

```bash
uv run python -m toys.dilemma.dilemma -r 100 -n 10
```

```
   #  strategy        total  wins  losses
-----------------------------------------
   1  tft             2323     0     3
   2  all_c           2187     0     5
   3  grudger         1419     1     1
   4  suspicious_tft  1268     3     0
   ...
```

Same seed, same result. First place usually goes to something generous-but-not-
soft (classic IPD lesson).

Stdlib only.
