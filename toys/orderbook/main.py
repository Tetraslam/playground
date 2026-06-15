"""orderbook — a tiny market-microstructure simulator you can look at.

A continuous double-auction matching engine (price-time priority) fed by a mix
of agents: liquidity providers posting limit orders around the mid, noise
traders crossing the spread, and an occasional informed trader pushing toward a
hidden "true value". Run it for N steps; it renders an SVG showing the live
order-book depth ladder + the price tape (trade history) + key microstructure
stats (spread, mid, depth).

    uv run python toys/orderbook/main.py --steps 4000 --out scratch/book.svg
    uv run python toys/orderbook/main.py --seed crash --true-value 90

Teaches: bid/ask spread, book depth, price-time priority, price impact, how a
price discovers a hidden value. Stdlib only.

Drawn from the seed bank topic "market microstructure" — the toy is invented
from the bare topic (the diversified ideation pipeline).
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import math
import os
from dataclasses import dataclass, field


class Rng:
    """Deterministic splitmix64 PRNG seeded from a string."""

    def __init__(self, seed: str):
        self.s = int.from_bytes(hashlib.blake2b(seed.encode(), digest_size=8).digest(), "little")

    def _next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def rand(self) -> float:
        return (self._next() >> 11) / float(1 << 53)

    def randint(self, a: int, b: int) -> int:
        return a + int(self.rand() * (b - a + 1))

    def gauss(self) -> float:
        # Box-Muller
        u1 = max(1e-9, self.rand())
        u2 = self.rand()
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


@dataclass(order=True)
class Order:
    # heap orders by (price-priority, seq) — see book sides for sign handling
    sort_key: tuple
    price: int = field(compare=False)
    qty: int = field(compare=False)
    side: str = field(compare=False)  # "buy" / "sell"
    seq: int = field(compare=False)


class Book:
    """Continuous double auction with price-time priority. Prices are integer ticks."""

    def __init__(self):
        self.bids: list[Order] = []  # max-heap via negated price
        self.asks: list[Order] = []  # min-heap
        self.seq = 0
        self.trades: list[tuple[int, int]] = []  # (step, price)
        self.mid_history: list[float] = []

    def best_bid(self) -> int | None:
        self._clean(self.bids)
        return -self.bids[0].sort_key[0] if self.bids else None

    def best_ask(self) -> int | None:
        self._clean(self.asks)
        return self.asks[0].sort_key[0] if self.asks else None

    def _clean(self, heap: list[Order]) -> None:
        while heap and heap[0].qty <= 0:
            heapq.heappop(heap)

    def add_limit(self, side: str, price: int, qty: int) -> None:
        self.seq += 1
        if side == "buy":
            heapq.heappush(self.bids, Order((-price, self.seq), price, qty, side, self.seq))
        else:
            heapq.heappush(self.asks, Order((price, self.seq), price, qty, side, self.seq))

    def market(self, side: str, qty: int, step: int) -> None:
        """Cross the spread, consuming the opposite side, recording trades."""
        if side == "buy":
            while qty > 0:
                self._clean(self.asks)
                if not self.asks:
                    break
                top = self.asks[0]
                take = min(qty, top.qty)
                top.qty -= take
                qty -= take
                self.trades.append((step, top.price))
        else:
            while qty > 0:
                self._clean(self.bids)
                if not self.bids:
                    break
                top = self.bids[0]
                take = min(qty, top.qty)
                top.qty -= take
                qty -= take
                self.trades.append((step, top.price))

    def depth(self, side: str, levels: int) -> list[tuple[int, int]]:
        """Aggregate resting qty by price for the top `levels` (for the ladder)."""
        heap = self.bids if side == "buy" else self.asks
        agg: dict[int, int] = {}
        for o in heap:
            if o.qty > 0:
                agg[o.price] = agg.get(o.price, 0) + o.qty
        items = sorted(agg.items(), reverse=(side == "buy"))
        return items[:levels]


def simulate(seed: str, steps: int, true_value: int) -> Book:
    rng = Rng(seed)
    book = Book()
    mid = true_value  # start at fair value

    # seed initial liquidity around the mid
    for d in range(1, 12):
        book.add_limit("buy", mid - d, rng.randint(2, 9))
        book.add_limit("sell", mid + d, rng.randint(2, 9))

    for step in range(steps):
        bb, ba = book.best_bid(), book.best_ask()
        if bb is None or ba is None:
            cur_mid = mid
        else:
            cur_mid = (bb + ba) / 2
        book.mid_history.append(cur_mid)

        roll = rng.rand()
        if roll < 0.55:
            # liquidity provider: post a limit near the touch, replenishing depth
            side = "buy" if rng.rand() < 0.5 else "sell"
            off = 1 + int(abs(rng.gauss()) * 3)
            px = int(cur_mid) - off if side == "buy" else int(cur_mid) + off
            book.add_limit(side, px, rng.randint(1, 6))
        elif roll < 0.85:
            # noise trader: market order, random direction
            side = "buy" if rng.rand() < 0.5 else "sell"
            book.market(side, rng.randint(1, 5), step)
        else:
            # informed trader: pushes price toward the hidden true value
            if cur_mid < true_value:
                book.market("buy", rng.randint(2, 7), step)
            elif cur_mid > true_value:
                book.market("sell", rng.randint(2, 7), step)

        # occasionally cancel stale far-from-touch orders (keeps book tight)
        if rng.rand() < 0.05:
            for heap in (book.bids, book.asks):
                if heap and rng.rand() < 0.5:
                    victim = heap[rng.randint(0, len(heap) - 1)]
                    victim.qty = max(0, victim.qty - rng.randint(1, 3))

    return book


def render(book: Book, true_value: int, seed: str, size: int) -> str:
    W = H = size
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="#0d1117"/>',
    ]
    # layout: left = depth ladder, right = price tape
    pad = 18
    ladder_w = int(W * 0.42)
    tape_x = ladder_w + pad * 2
    tape_w = W - tape_x - pad

    bb, ba = book.best_bid(), book.best_ask()
    mid = (bb + ba) / 2 if bb and ba else true_value
    spread = (ba - bb) if (bb and ba) else 0

    # ---- depth ladder (top 12 levels each side) ----
    levels = 12
    bids = book.depth("buy", levels)
    asks = book.depth("sell", levels)
    maxq = max([q for _, q in bids + asks] + [1])
    row_h = (H - pad * 4) / (levels * 2 + 1)
    cy = pad * 2
    parts.append(
        f'<text x="{pad}" y="{pad+2}" fill="#8b949e" font-family="monospace" '
        f'font-size="11">order book — depth (qty per price)</text>'
    )
    # asks descending (highest at top)
    y = cy
    for px, q in reversed(asks):
        w = (q / maxq) * (ladder_w - 70)
        parts.append(
            f'<rect x="{pad+60}" y="{y:.1f}" width="{w:.1f}" height="{row_h*0.8:.1f}" '
            f'fill="#f85149" opacity="0.85"/>'
            f'<text x="{pad}" y="{y+row_h*0.65:.1f}" fill="#f85149" '
            f'font-family="monospace" font-size="10">{px}</text>'
        )
        y += row_h
    # mid line
    parts.append(
        f'<line x1="{pad}" y1="{y+row_h*0.4:.1f}" x2="{pad+ladder_w:.1f}" '
        f'y2="{y+row_h*0.4:.1f}" stroke="#58a6ff" stroke-width="1" stroke-dasharray="3 2"/>'
        f'<text x="{pad+ladder_w-90:.0f}" y="{y+row_h*0.2:.1f}" fill="#58a6ff" '
        f'font-family="monospace" font-size="9">mid {mid:.1f}  sprd {spread}</text>'
    )
    y += row_h
    # bids descending
    for px, q in bids:
        w = (q / maxq) * (ladder_w - 70)
        parts.append(
            f'<rect x="{pad+60}" y="{y:.1f}" width="{w:.1f}" height="{row_h*0.8:.1f}" '
            f'fill="#3fb950" opacity="0.85"/>'
            f'<text x="{pad}" y="{y+row_h*0.65:.1f}" fill="#3fb950" '
            f'font-family="monospace" font-size="10">{px}</text>'
        )
        y += row_h

    # ---- price tape (trades over time) ----
    parts.append(
        f'<text x="{tape_x}" y="{pad+2}" fill="#8b949e" font-family="monospace" '
        f'font-size="11">price tape — discovery toward true value {true_value}</text>'
    )
    series = book.mid_history
    if series:
        lo = min(min(series), true_value) - 2
        hi = max(max(series), true_value) + 2
        rng_v = (hi - lo) or 1
        n = len(series)

        def sx(i):
            return tape_x + (i / max(n - 1, 1)) * tape_w

        def sy(v):
            return pad * 2 + (1 - (v - lo) / rng_v) * (H - pad * 4)

        # true-value reference line
        parts.append(
            f'<line x1="{tape_x}" y1="{sy(true_value):.1f}" x2="{tape_x+tape_w:.1f}" '
            f'y2="{sy(true_value):.1f}" stroke="#d29922" stroke-width="1" '
            f'stroke-dasharray="4 3" opacity="0.7"/>'
        )
        # mid path
        d = "M " + " L ".join(f"{sx(i):.1f} {sy(v):.1f}" for i, v in enumerate(series))
        parts.append(f'<path d="{d}" fill="none" stroke="#58a6ff" stroke-width="1.4"/>')
        # trade prints as faint dots
        for st, px in book.trades[-600:]:
            i = min(st, n - 1)
            parts.append(
                f'<circle cx="{sx(i):.1f}" cy="{sy(px):.1f}" r="1" '
                f'fill="#c9d1d9" opacity="0.25"/>'
            )

    # footer stats
    n_trades = len(book.trades)
    parts.append(
        f'<text x="{pad}" y="{H-6}" fill="#6e7681" font-family="monospace" '
        f'font-size="10">seed "{seed}" · {n_trades} trades · final mid {mid:.1f} '
        f'· spread {spread} ticks</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="A tiny market-microstructure / order-book simulator.")
    ap.add_argument("--seed", default="market", help="PRNG seed (also the scenario name)")
    ap.add_argument("--steps", type=int, default=4000, help="simulation steps")
    ap.add_argument("--true-value", type=int, default=100, help="hidden fair value to discover")
    ap.add_argument("--out", default="", help="output SVG path (default: stdout)")
    ap.add_argument("--size", type=int, default=560, help="canvas size px")
    args = ap.parse_args()

    book = simulate(args.seed, args.steps, args.true_value)
    svg = render(book, args.true_value, args.seed, args.size)

    if not args.out:
        print(svg)
        return
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)

    bb, ba = book.best_bid(), book.best_ask()
    mid = (bb + ba) / 2 if bb and ba else args.true_value
    print(
        f'orderbook: "{args.seed}" -> {args.out}  '
        f"({len(book.trades)} trades, final mid {mid:.1f}, "
        f"true {args.true_value}, spread {(ba-bb) if bb and ba else '-'})"
    )


if __name__ == "__main__":
    main()
