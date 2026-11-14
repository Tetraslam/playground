"""Matplotlib figures for rtosaurus runs.

- plot_run(trace, out_png)       temperature / setpoint / ambient, heater + fan, event markers
- plot_gantt(trace, out_png)     which kernel task was running when
- plot_campaign(results, out_png) survival vs fault rate across seeded fault runs

Trace samples are dicts with keys t, plant_t, temp, setpoint, heater, fan, task,
events (list[str]) and optionally ambient. Campaign results are dicts with
rate (faults per sim second), seed, survived (bool), and optionally boiled,
max_temp, faults, wdogs.
"""

from __future__ import annotations

import math
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BG = "#14161b"
FG = "#d8dee9"
GRID = "#2a2f3a"
C_TEMP = "#ff8c42"
C_SET = "#7fdbca"
C_AMB = "#6c7a96"
C_HEAT = "#ff5d5d"
C_FAN = "#5da9ff"
EVENT_COLORS = {
    "fault": "#ff4d6d",
    "wdog": "#ffd23f",
    "inject": "#c77dff",
    "door": "#8d99ae",
    "boiled": "#ff0000",
    "halt": "#ff0000",
    "boot": "#a3be8c",
    "stuck": "#c77dff",
    "sensor": "#06d6a0",  # firmware's own detection, e.g. "sensor failed: heater off"
}
# chatter that the trace already shows (setpoint line) or that would only clutter
SKIP_EVENT_PREFIXES = ("uart>", "knob", "button", "sensor recovered")
TASK_COLORS = [
    "#ff8c42",
    "#7fdbca",
    "#c77dff",
    "#5da9ff",
    "#ffd23f",
    "#ff5d5d",
    "#a3be8c",
    "#ebcb8b",
    "#4c566a",
]


def _style(fig, axes) -> None:
    fig.patch.set_facecolor(BG)
    for ax in axes:
        ax.set_facecolor(BG)
        ax.tick_params(colors=FG, labelsize=8)
        for s in ax.spines.values():
            s.set_color(GRID)
        ax.grid(True, color=GRID, lw=0.6)
        ax.xaxis.label.set_color(FG)
        ax.yaxis.label.set_color(FG)
        ax.title.set_color(FG)


def _event_kind(ev: str) -> str:
    for k in EVENT_COLORS:
        if ev.startswith(k) or (k == "door" and "door" in ev):
            return k
    return "inject" if "inject" in ev else "other"


def _events(trace: list[dict]) -> list[tuple[float, str, str]]:
    out = []
    for s in trace:
        for ev in s.get("events") or []:
            if not ev.startswith(SKIP_EVENT_PREFIXES):
                out.append((s["t"], ev, _event_kind(ev)))
    return out


def _stuck_spans(trace: list[dict]) -> list[tuple[float, float]]:
    """Stuck-sensor windows: 'inject stuck-sensor ...' until 'sensor recovered'."""
    spans, start = [], None
    for s in trace:
        for ev in s.get("events") or []:
            if ev.startswith("inject stuck-sensor") and start is None:
                start = s["t"]
            elif ev.startswith("sensor recovered") and start is not None:
                spans.append((start, s["t"]))
                start = None
    if start is not None and trace:
        spans.append((start, trace[-1]["t"]))
    return spans


def _door_spans(trace: list[dict]) -> list[tuple[float, float]]:
    spans, start = [], None
    if any("door_open" in s for s in trace):  # per-sample flag (machine trace)
        for s in trace:
            if s.get("door_open") and start is None:
                start = s["t"]
            elif not s.get("door_open") and start is not None:
                spans.append((start, s["t"]))
                start = None
        if start is not None:
            spans.append((start, trace[-1]["t"]))
        return spans
    for s in trace:
        for ev in s.get("events") or []:
            if ev == "door open" and start is None:
                start = s["t"]
            elif ev == "door closed" and start is not None:
                spans.append((start, s["t"]))
                start = None
    if start is not None and trace:
        spans.append((start, trace[-1]["t"]))
    return spans


def plot_run(trace: list[dict], out_png: str, title: str = "") -> None:
    """Temperature/setpoint (+ambient) on top, heater/fan duty below, events as markers."""
    if not trace:
        raise ValueError("empty trace")
    t = [s["t"] for s in trace]
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1.2], "hspace": 0.08}
    )
    _style(fig, (ax1, ax2))

    for a, b in _door_spans(trace):
        for ax in (ax1, ax2):
            ax.axvspan(a, b, color=EVENT_COLORS["door"], alpha=0.15, lw=0)
    stuck = _stuck_spans(trace)
    for a, b in stuck:
        ax1.axvspan(a, b, color=EVENT_COLORS["stuck"], alpha=0.12, lw=0)
    if any("ambient" in s for s in trace):
        ax1.plot(t, [s.get("ambient", math.nan) for s in trace], color=C_AMB, lw=1, label="ambient")
    ax1.step(
        t,
        [s["setpoint"] for s in trace],
        where="post",
        color=C_SET,
        lw=1.4,
        ls="--",
        label="setpoint",
    )
    ax1.plot(t, [s["temp"] for s in trace], color=C_TEMP, lw=1.6, label="tank")
    ax1.axhline(100, color=EVENT_COLORS["boiled"], lw=0.8, ls=":", alpha=0.7)
    ax1.axhline(90, color=EVENT_COLORS["wdog"], lw=0.6, ls=":", alpha=0.5)
    ax1.set_ylabel("°C")

    ax2.fill_between(
        t, [s["heater"] for s in trace], step="post", color=C_HEAT, alpha=0.55, lw=0, label="heater"
    )
    ax2.step(t, [s["fan"] for s in trace], where="post", color=C_FAN, lw=1.2, label="fan")
    ax2.set_ylim(-0.05, 1.08)
    ax2.set_ylabel("duty")
    ax2.set_xlabel("sim time (s)")

    lo, hi = ax1.get_ylim()
    seen = set()
    for te, _ev, kind in _events(trace):
        if kind == "door":
            continue
        c = EVENT_COLORS.get(kind, FG)
        lab = kind if kind not in seen else None
        seen.add(kind)
        ax1.axvline(te, color=c, lw=0.9, alpha=0.8, label=lab)
        ax2.axvline(te, color=c, lw=0.9, alpha=0.8)
    if _door_spans(trace):
        ax1.axvspan(math.nan, math.nan, color=EVENT_COLORS["door"], alpha=0.3, label="door open")
    if stuck:
        ax1.axvspan(
            math.nan, math.nan, color=EVENT_COLORS["stuck"], alpha=0.25, label="sensor stuck"
        )
    ax1.set_ylim(lo, hi)

    for ax in (ax1, ax2):
        leg = ax.legend(loc="upper left", fontsize=8, facecolor=BG, edgecolor=GRID, ncol=4)
        for txt in leg.get_texts():
            txt.set_color(FG)
    if title:
        ax1.set_title(title, fontsize=11)
    fig.savefig(out_png, dpi=120, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def _gantt_intervals(trace: list[dict]) -> dict[int, list[tuple[float, float, float]]]:
    """task -> [(start, width, share)]. With `task_cycles` (cycles per task since the
    previous sample) each interval (t_prev, t] gets a bar in every lane that ran, with
    share = that task's fraction of the interval's cycles. Without it, fall back to
    point-sampled `task` (share 1)."""
    out: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
    first_dt = trace[1]["t"] - trace[0]["t"] if len(trace) > 1 else 1e-3
    for i, s in enumerate(trace):
        t0 = trace[i - 1]["t"] if i else s["t"] - first_dt
        w = s["t"] - t0
        tc = s.get("task_cycles")
        if tc is not None:
            total = sum(tc.values())
            for k, c in tc.items():
                if c > 0 and total > 0:
                    out[int(k)].append((t0, w, c / total))
        elif s.get("task") is not None:
            # point sample: the task seen at t runs until the next sample
            w2 = trace[i + 1]["t"] - s["t"] if i + 1 < len(trace) else first_dt
            out[int(s["task"])].append((s["t"], w2, 1.0))
    return out


def plot_gantt(
    trace: list[dict], out_png: str, title: str = "task schedule", names: dict | None = None
) -> None:
    """One lane per task index (8 = kernel idle). Bar height = the task's share of the
    CPU in that sample interval; the lane label carries its overall CPU share."""
    if not trace:
        raise ValueError("empty trace")
    iv = _gantt_intervals(trace)
    lanes = sorted(iv)
    busy = {k: sum(w * sh for _, w, sh in iv[k]) for k in lanes}
    tot = sum(busy.values()) or 1.0
    fig, ax = plt.subplots(figsize=(11, 0.5 * max(len(lanes), 2) + 1.4))
    _style(fig, (ax,))
    names = {int(k): v for k, v in (names or {}).items()}
    # sub-pixel bars get dropped by the rasterizer on long runs: floor at ~2 px
    min_w = (trace[-1]["t"] - trace[0]["t"]) / 500 if len(trace) > 1 else 0.0
    for y, k in enumerate(lanes):
        xs = [a for a, _, _ in iv[k]]
        ws = [max(w, min_w) for _, w, _ in iv[k]]
        # sqrt so a 2% task is still a visible sliver; floor keeps any run visible
        hs = [0.8 * max(0.12, math.sqrt(sh)) for _, _, sh in iv[k]]
        ax.bar(
            xs,
            hs,
            width=ws,
            bottom=[y + 0.4 - h for h in hs],
            align="edge",
            color=TASK_COLORS[k % len(TASK_COLORS)],
            lw=0,
            antialiased=False,  # AA fades ~1 px bars to nothing; hard pixels always land
            snap=True,
        )
    ax.set_yticks(range(len(lanes)))
    ax.set_yticklabels(
        [
            f"{names.get(k, 'idle' if k == 8 else f't{k}')}  {100 * busy[k] / tot:.1f}%"
            for k in lanes
        ]
    )
    for te, _ev, kind in _events(trace):
        if kind in ("fault", "wdog", "inject", "boot", "halt"):
            ax.axvline(te, color=EVENT_COLORS[kind], lw=0.9, alpha=0.8)
    ax.set_xlabel("sim time (s)")
    ax.set_ylim(-0.6, len(lanes) - 0.4)
    ax.set_title(title + "  (bar height = CPU share per sample)", fontsize=11)
    ax.invert_yaxis()
    fig.savefig(out_png, dpi=120, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Success fraction and its Wilson score interval."""
    if n == 0:
        return math.nan, math.nan, math.nan
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def plot_campaign(results: list[dict], out_png: str, title: str = "fault campaign") -> None:
    """Survival fraction (Wilson 95% CI) vs fault rate; max tank temp per run on the right."""
    if not results:
        raise ValueError("no results")
    groups: dict[str, dict[float, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in results:
        groups[str(r.get("kind", "survived"))][float(r["rate"])].append(r)
    all_rates = sorted({float(r["rate"]) for r in results})

    has_temp = any("max_temp" in r for r in results)
    fig, axes = plt.subplots(
        1, 2 if has_temp else 1, figsize=(11 if has_temp else 6.5, 4.2), squeeze=False
    )
    axes = axes[0]
    _style(fig, axes)
    ax = axes[0]
    for gi, (kind, by_rate) in enumerate(sorted(groups.items())):
        rates = sorted(by_rate)
        surv = [
            wilson(sum(bool(r["survived"]) for r in by_rate[x]), len(by_rate[x])) for x in rates
        ]
        c = C_SET if len(groups) == 1 else TASK_COLORS[(gi + 1) % len(TASK_COLORS)]
        ax.fill_between(
            rates, [s[1] for s in surv], [s[2] for s in surv], color=c, alpha=0.15, lw=0
        )
        ax.plot(rates, [s[0] for s in surv], "o-", color=c, lw=1.6, ms=5, label=kind)
    if any(r.get("boiled") for r in results):
        by_rate = defaultdict(list)
        for r in results:
            by_rate[float(r["rate"])].append(r)
        boil = [sum(bool(r.get("boiled")) for r in by_rate[x]) / len(by_rate[x]) for x in all_rates]
        ax.plot(
            all_rates,
            boil,
            "s--",
            color=EVENT_COLORS["boiled"],
            lw=1.2,
            ms=4,
            label="boiled (all kinds)",
        )
    rates = all_rates
    ax.set_ylim(-0.03, 1.03)
    ax.set_xlabel("fault rate (faults / sim s)")
    ax.set_ylabel("fraction of runs survived")
    ax.set_title(f"{title}  (n={len(results)})", fontsize=11)
    leg = ax.legend(fontsize=8, facecolor=BG, edgecolor=GRID)
    for txt in leg.get_texts():
        txt.set_color(FG)

    if has_temp:
        ax = axes[1]
        kinds = sorted(groups)
        span = (rates[-1] - rates[0]) or 1
        for r in results:
            if r.get("max_temp") is None or r["max_temp"] != r["max_temp"]:  # missing / NaN
                continue
            ki = kinds.index(str(r.get("kind", "survived")))
            c = C_SET if len(kinds) == 1 else TASK_COLORS[(ki + 1) % len(TASK_COLORS)]
            # deterministic jitter: kinds side by side, seeds spread within
            off = (ki - (len(kinds) - 1) / 2) * 0.05 + (
                (int(r.get("seed", 0)) * 37) % 11 / 10 - 0.5
            ) * 0.03
            x = float(r["rate"]) + off * span
            if r["survived"]:
                ax.scatter(x, r["max_temp"], s=16, color=c, alpha=0.8, lw=0)
            else:
                ax.scatter(x, r["max_temp"], s=26, color=c, alpha=0.95, marker="x", lw=1.3)
        ax.axhline(100, color=EVENT_COLORS["boiled"], lw=0.8, ls=":")
        ax.axhline(90, color=EVENT_COLORS["wdog"], lw=0.6, ls=":")
        ax.set_xlabel("fault rate (faults / sim s)")
        ax.set_ylabel("max tank temp (°C)")
        ax.set_title("peak temperature per run (x = did not survive)", fontsize=10)
    fig.savefig(out_png, dpi=120, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


if __name__ == "__main__":
    import random
    import sys
    from pathlib import Path

    from .plant import demo_pid

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "examples")
    out.mkdir(parents=True, exist_ok=True)
    tr = demo_pid(seconds=400, seed=3)
    tr[1500]["events"].append("inject ram-flip 0x0123")
    tr[1510]["events"].append("fault t1")
    tr[2200]["events"].append("wdog")
    rng = random.Random(0)
    for i, s in enumerate(tr):  # fake schedule for the gantt preview
        s["task"] = 8 if (i // 3) % 5 else rng.choice([0, 1, 2, 3])
    plot_run(
        tr,
        str(out / "plant_pid_reference.png"),
        title="host-side reference PID on the plant (not firmware)",
    )
    plot_gantt(tr[:300], str(out / "gantt_preview.png"), title="gantt preview (synthetic schedule)")
    res = []
    for rate in (0, 0.5, 1, 2, 4, 8):
        for seed in range(20):
            ok = rng.random() > rate / 10
            res.append(
                {
                    "rate": rate,
                    "seed": seed,
                    "survived": ok,
                    "boiled": not ok and rng.random() < 0.4,
                    "max_temp": 46 + rng.random() * 5 + (0 if ok else rng.random() * 50),
                }
            )
    plot_campaign(res, str(out / "campaign_preview.png"), title="campaign preview (synthetic)")
    print("wrote", *sorted(p.name for p in out.glob("*.png")))
