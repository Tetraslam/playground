# orderbook

A tiny **market-microstructure** simulator you can look at. A continuous
double-auction matching engine (price-time priority) is fed by a mix of agents;
it renders the live order book + the price tape as an SVG.

```bash
uv run python toys/orderbook/main.py --steps 4000 --out scratch/book.svg
uv run python toys/orderbook/main.py --seed crash --true-value 70 --out scratch/crash.svg
# view: rsvg-convert scratch/book.svg -o scratch/book.png
```

## What you're looking at

- **Left — depth ladder:** resting limit orders aggregated by price. Red = asks
  (above the mid), green = bids (below). Bar length = quantity at that price.
  The dashed blue line is the mid; the spread is labeled.
- **Right — price tape:** the mid price over time (blue), with the hidden **true
  value** as a gold dashed line. Faint dots are trade prints. Watch the price
  *discover* the true value as informed traders push it there.

## The agents

- **Liquidity providers (~55%)** post limit orders near the touch — they make
  the book deep and the spread tight.
- **Noise traders (~30%)** send market orders in random directions — they move
  price around and pay the spread.
- **Informed traders (~15%)** push the price toward a hidden true value — they
  are why price discovery happens.

Deterministic per `--seed`. Teaches: bid/ask spread, book depth, price-time
priority, price impact, and price discovery.

Built from the seed-bank topic **"market microstructure"** — the toy was invented
from the bare topic (the diversified ideation pipeline, off the worldbuilding
theme).
