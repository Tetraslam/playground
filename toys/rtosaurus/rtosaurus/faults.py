"""Fault injection + campaigns (owner: agent 1).

Injectors fire as Poisson processes (rate = expected events per sim second),
driven from Machine sample hooks, all from one seeded RNG so runs replay exactly.

    ram-flip      flip one bit in a random firmware word (code or data)
    stack-flip    flip one bit in the task stack region (just below RAM_TOP)
    reg-flip      flip one bit in a random CPU register (r0..r7, incl. sp)
    stuck-sensor  temperature sensor freezes at a plausible-but-wrong value for a while
    irq-storm     a burst of garbage bytes on the UART (rx irq storm + queue pressure)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from rtosaurus import isa

KINDS = ["ram-flip", "stack-flip", "reg-flip", "stuck-sensor", "irq-storm"]
STACK_SPAN = 0x400  # words below RAM_TOP treated as "stack"


@dataclass
class Injector:
    kind: str
    rate: float  # events per sim second
    _stuck_until: float = field(default=-1.0, repr=False)

    def fire(self, m, rng: random.Random) -> str | None:
        k = self.kind
        if k == "ram-flip":
            addr = rng.choice(_image_addrs(m))
            bit = rng.randrange(16)
            m.bus.mem[addr] ^= 1 << bit
            return f"inject ram-flip {_where(m, addr)} b{bit}"
        if k == "stack-flip":
            addr = isa.RAM_TOP - rng.randrange(STACK_SPAN)
            bit = rng.randrange(16)
            m.bus.mem[addr] ^= 1 << bit
            return f"inject stack-flip 0x{addr:04x} b{bit}"
        if k == "reg-flip":
            r = rng.randrange(8)
            bit = rng.randrange(16)
            m.cpu.regs[r] ^= 1 << bit
            return f"inject reg-flip r{r} b{bit}"
        if k == "stuck-sensor":
            if m.plant.sensor_override is not None:
                return None
            # a cold reading is the dangerous lie: the controller heats harder
            val = rng.uniform(5.0, 30.0)
            m.plant.sensor_override = val
            self._stuck_until = m.t + rng.uniform(2.0, 8.0)
            return f"inject stuck-sensor {val:.1f}C"
        if k == "irq-storm":
            n = rng.randrange(16, 64)
            m.bus.uart_feed("".join(chr(rng.randrange(33, 127)) for _ in range(n)))
            return f"inject irq-storm {n}B"
        raise ValueError(f"unknown fault kind {k!r} (choose from {KINDS})")

    def update(self, m) -> str | None:
        if self.kind == "stuck-sensor" and m.plant.sensor_override is not None and m.t >= self._stuck_until:
            m.plant.sensor_override = None
            return "sensor recovered"
        return None


def _image_addrs(m) -> list[int]:
    if not hasattr(m, "_fault_addrs"):
        m._fault_addrs = sorted(a for a in m.image.words if a >= isa.NUM_VECTORS)
    return m._fault_addrs


def _where(m, addr: int) -> str:
    """0x0123 (+label+off) for readable event logs."""
    best = None
    for name, a in m.image.symbols.items():
        if a <= addr and (best is None or a > best[1]) and a in m.image.words:
            best = (name, a)
    tag = f" {best[0]}+{addr - best[1]}" if best else ""
    return f"0x{addr:04x}{tag}"


class FaultSchedule:
    """Attach to a Machine: m.hooks.append(schedule)."""

    def __init__(self, injectors: list[Injector], seed: int = 0, start: float = 0.0):
        self.injectors = injectors
        self.rng = random.Random(seed ^ 0x5EED)
        self.start = start  # no injections before this sim time (let the plant settle)

    def __call__(self, m, dt: float) -> None:
        for inj in self.injectors:
            msg = inj.update(m)
            if msg:
                m.event(msg)
            if m.t < self.start or inj.rate <= 0:
                continue
            # Poisson thinning: P(event in dt) ~ rate*dt for small dt
            if self.rng.random() < inj.rate * dt:
                msg = inj.fire(m, self.rng)
                if msg:
                    m.event(msg)


def inject_now(m, kind: str, rng: random.Random | None = None) -> str | None:
    """Fire one fault immediately (for the dashboard's 'f' key). Logs it as a machine event.

    Registers a recovery hook once per machine so a stuck sensor un-sticks on its own.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown fault kind {kind!r} (choose from {KINDS})")
    manual = getattr(m, "_manual_injectors", None)
    if manual is None:
        manual = m._manual_injectors = {}

        def recover(mm, dt):
            for inj in manual.values():
                msg = inj.update(mm)
                if msg:
                    mm.event(msg)

        m.hooks.append(recover)
    inj = manual.setdefault(kind, Injector(kind, 0.0))
    msg = inj.fire(m, rng or random.Random())
    if msg:
        m.event(msg)
    return msg


def parse_spec(spec: str) -> list[Injector]:
    """'ram-flip:0.5,stuck-sensor:0.1' -> injectors."""
    out = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        kind, _, rate = part.partition(":")
        if kind not in KINDS:
            raise ValueError(f"unknown fault kind {kind!r} (choose from {KINDS})")
        out.append(Injector(kind, float(rate or 1.0)))
    return out


# ---------------------------------------------------------------------------
# campaigns


def survived(s: dict, tol: float = 5.0) -> bool:
    """Tank never boiled, CPU still running, and still roughly tracking the setpoint."""
    return (
        not s["boiled"]
        and not s["halted"]
        and s["mean_abs_err"] is not None
        and abs(s["final_temp"] - s["setpoint"]) <= tol
    )


def one_run(args: tuple) -> dict:
    kind, rate, seed, seconds, settle = args
    from rtosaurus.machine import Machine, build_firmware

    m = Machine(build_firmware(), seed=seed, sample_cycles=2000)
    if rate > 0:
        m.hooks.append(FaultSchedule([Injector(kind, rate)], seed=seed, start=settle))
    m.run_seconds(seconds)
    s = m.summary()
    s |= {"kind": kind, "rate": rate, "seed": seed, "setpoint": m.plant.setpoint}
    s["survived"] = survived(s)
    return s


def campaign(
    kinds: list[str], rates: list[float], seeds: int, seconds: float, settle: float = 10.0, jobs: int | None = None, log=print
) -> list[dict]:
    """Every (kind, rate, seed) run, in parallel processes. Returns summaries."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    jobs_list = [(k, r, s, seconds, settle) for k in kinds for r in rates for s in range(seeds)]
    results = []
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(one_run, j): j for j in jobs_list}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            results.append(r)
            log(
                f"[{i}/{len(jobs_list)}] {r['kind']:<12} rate={r['rate']:<5g} seed={r['seed']:<3} "
                f"{'SURVIVED' if r['survived'] else 'died    '} max={r['max_temp']:.1f}C "
                f"faults={r['task_faults']} wdog={r['wdog_resets']}{' HALT' if r['halted'] else ''}"
            )
    results.sort(key=lambda r: (r["kind"], r["rate"], r["seed"]))
    return results


def survival_table(results: list[dict]) -> str:
    rates = sorted({r["rate"] for r in results})
    kinds = sorted({r["kind"] for r in results})
    lines = ["kind          " + "".join(f"{r:>8g}" for r in rates) + "   (survival by rate, events/sim-s)"]
    for k in kinds:
        cells = []
        for rate in rates:
            rs = [r for r in results if r["kind"] == k and r["rate"] == rate]
            cells.append(f"{sum(r['survived'] for r in rs) / len(rs):>8.0%}" if rs else f"{'-':>8}")
        lines.append(f"{k:<14}" + "".join(cells))
    return "\n".join(lines)
