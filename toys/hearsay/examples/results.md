| system | decoder | clean | 10 dB | 0 dB |
|---|---|---|---|---|
| cortex (stdp) | vote | 0.21 | 0.19 | 0.07 |
| cortex (stdp) | template | 0.96 | 0.59 | 0.15 |
| cortex (stdp) | poisson | 0.99 | 0.89 | 0.21 |
| cortex (untrained) | vote | 0.45 | 0.17 | 0.11 |
| cortex (untrained) | template | 0.95 | 0.53 | 0.20 |
| cortex (untrained) | poisson | 0.96 | 0.80 | 0.21 |
| nerve (no cortex) | vote | 0.30 | 0.09 | 0.07 |
| nerve (no cortex) | template | 0.93 | 0.42 | 0.31 |
| nerve (no cortex) | poisson | 0.99 | 0.80 | 0.21 |

lesion (10 dB test, decoder not refit), fraction killed -> accuracy:

| killed | cortex poisson | cortex template | nerve poisson | nerve template |
|---|---|---|---|---|
| 0.0 | 0.89 | 0.59 | 0.80 | 0.42 |
| 0.1 | 0.89 | 0.59 | 0.82 | 0.47 |
| 0.2 | 0.89 | 0.59 | 0.80 | 0.46 |
| 0.3 | 0.89 | 0.60 | 0.80 | 0.49 |
| 0.4 | 0.90 | 0.60 | 0.78 | 0.50 |
| 0.5 | 0.89 | 0.60 | 0.77 | 0.52 |
| 0.6 | 0.88 | 0.56 | 0.78 | 0.49 |
| 0.7 | 0.89 | 0.56 | 0.74 | 0.52 |
| 0.8 | 0.88 | 0.54 | 0.68 | 0.50 |
| 0.9 | 0.82 | 0.46 | 0.54 | 0.44 |
