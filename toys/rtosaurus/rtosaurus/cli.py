"""rtosaurus CLI (owner: agent 1).

uv run python -m rtosaurus run [--seconds 30] [--inject data-flip:0.5] [--at 10:s60] [--plot run.png]
uv run python -m rtosaurus dash [--inject ...]
uv run python -m rtosaurus campaign [--kinds ...] [--rates 0,0.5,1,2] [--seeds 6] [--plot c.png]
uv run python -m rtosaurus asm [file.s] [--listing]
uv run python -m rtosaurus disasm [--start ADDR] [--count N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rtosaurus import isa


def _machine(a):
    from rtosaurus.faults import FaultSchedule, parse_spec
    from rtosaurus.machine import Machine, build_firmware

    m = Machine(
        build_firmware(a.firmware) if a.firmware else build_firmware(),
        seed=a.seed,
        safety=not a.no_safety,
    )
    if a.setpoint is not None:
        m.plant.setpoint = a.setpoint
    if a.inject:
        m.hooks.append(FaultSchedule(parse_spec(a.inject), seed=a.seed, start=a.settle))
    return m


def _script(spec: list[str]) -> list[tuple[float, str]]:
    """--at 10:s60  --at 20:knob=35  -> sorted (time, action)."""
    out = []
    for s in spec or []:
        t, _, what = s.partition(":")
        out.append((float(t), what))
    return sorted(out)


def cmd_run(a) -> int:
    m = _machine(a)
    script = _script(a.at)
    t0 = time.time()
    shown = 0
    step = 0.25
    while m.t < a.seconds - 1e-9:
        while script and script[0][0] <= m.t:
            _, what = script.pop(0)
            if what.startswith("knob="):
                m.set_setpoint(float(what[5:]))
            else:
                m.send(what.replace("\\n", "\n") + ("" if what.endswith("\\n") else "\n"))
        m.run_seconds(min(step, a.seconds - m.t))
        if not a.quiet:
            text = m.uart_text()
            if len(text) > shown:
                sys.stdout.write(text[shown:])
                sys.stdout.flush()
                shown = len(text)
    wall = time.time() - t0
    s = m.summary()
    print(
        f"\n--- {m.t:.2f} sim s in {wall:.1f} s wall ({m.bus.cycles / max(wall, 1e-9) / 1e3:.0f}k cycles/s)",
        file=sys.stderr,
    )
    print(json.dumps(s), file=sys.stderr)
    for t, e in m.event_log:
        if not e.startswith("uart>") or a.verbose:
            print(f"  {t:8.3f}  {e}", file=sys.stderr)
    if a.plot or a.gantt:
        from rtosaurus import plots

        names = {t["id"]: t["name"] for t in m.tasks()}
        if a.plot:
            plots.plot_run(m.trace, a.plot, title=a.title or _title(a))
            print(f"wrote {a.plot}", file=sys.stderr)
        if a.gantt:
            plots.plot_gantt(
                m.trace,
                a.gantt,
                **({"names": names} if _accepts(plots.plot_gantt, "names") else {}),
            )
            print(f"wrote {a.gantt}", file=sys.stderr)
    if a.trace_json:
        Path(a.trace_json).write_text(
            json.dumps({"summary": s, "events": m.event_log, "trace": m.trace})
        )
    return 0 if not s["boiled"] else 2


def _title(a) -> str:
    return f"rtosaurus seed={a.seed}" + (f"  inject={a.inject}" if a.inject else "")


def _accepts(fn, name: str) -> bool:
    import inspect

    return name in inspect.signature(fn).parameters


def cmd_dash(a) -> int:
    from rtosaurus import dash

    dash.run(_machine(a))
    return 0


def cmd_campaign(a) -> int:
    from rtosaurus.faults import campaign, survival_table

    kinds = a.kinds.split(",")
    rates = [float(x) for x in a.rates.split(",")]
    t0 = time.time()
    res = campaign(
        kinds,
        rates,
        a.seeds,
        a.seconds,
        settle=a.settle,
        jobs=a.jobs,
        log=lambda s: print(s, file=sys.stderr),
        safety=not a.no_safety,
    )
    print(survival_table(res))
    print(f"({len(res)} runs, {time.time() - t0:.0f} s wall)", file=sys.stderr)
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    if a.plot:
        from rtosaurus import plots

        plots.plot_campaign(res, a.plot)
        print(f"wrote {a.plot}", file=sys.stderr)
    return 0


def cmd_asm(a) -> int:
    from rtosaurus.asm import assemble_file
    from rtosaurus.machine import FIRMWARE

    img = assemble_file(a.file or str(FIRMWARE / "main.s"))
    n = len(img.words)
    print(f"{n} words, {len(img.lines)} instructions, {len(img.symbols)} symbols", file=sys.stderr)
    if a.listing:
        from rtosaurus.disasm import disasm

        for addr in sorted(img.lines):
            w0, w1 = img.words.get(addr, 0), img.words.get(addr + 1, 0)
            print(
                f"{addr:04x}  {w0:04x} {w1:04x}  {disasm(w0, w1, img.symbols):<28} {img.lines[addr]}"
            )
    if a.symbols:
        consts = isa.mmio_constants()
        for k, v in sorted(img.symbols.items(), key=lambda kv: kv[1]):
            if k not in consts:
                print(f"{v:04x}  {k}")
    return 0


def cmd_disasm(a) -> int:
    from rtosaurus.disasm import disasm
    from rtosaurus.machine import build_firmware

    img = build_firmware(a.firmware) if a.firmware else build_firmware()
    rev = {v: k for k, v in img.symbols.items() if v in img.lines}
    start = int(a.start, 0) if a.start else isa.CODE_BASE
    for addr in range(start, start + 2 * a.count, 2):
        if addr in rev:
            print(f"{rev[addr]}:")
        w0, w1 = img.words.get(addr, 0), img.words.get(addr + 1, 0)
        print(f"  {addr:04x}  {disasm(w0, w1, img.symbols)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rtosaurus", description="an emulated MCU + RTOS keeping a water tank from boiling"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def machine_args(p):
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--firmware", help="top-level .s (default firmware/main.s)")
        p.add_argument(
            "--inject",
            help="fault spec, e.g. data-flip:0.5,stuck-sensor:0.1 (events per sim second)",
        )
        p.add_argument(
            "--settle", type=float, default=10.0, help="no injections before this sim time"
        )
        p.add_argument("--setpoint", type=float, help="initial setpoint knob (degC)")
        p.add_argument(
            "--no-safety",
            action="store_true",
            help="naive firmware: skip sensor plausibility checks",
        )

    p = sub.add_parser("run", help="run headless, stream UART, optional plots")
    machine_args(p)
    p.add_argument("--seconds", type=float, default=30.0, help="sim seconds")
    p.add_argument(
        "--at",
        action="append",
        help="scripted input TIME:TEXT (uart line) or TIME:knob=DEGC; repeatable",
    )
    p.add_argument("--plot", help="write temp/heater plot PNG")
    p.add_argument("--gantt", help="write task-schedule PNG")
    p.add_argument("--title")
    p.add_argument("--trace-json")
    p.add_argument("--quiet", action="store_true", help="don't stream UART")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("dash", help="live terminal dashboard")
    machine_args(p)
    p.set_defaults(fn=cmd_dash)

    p = sub.add_parser("campaign", help="many seeded fault runs -> survival table")
    p.add_argument(
        "--kinds", default="data-flip,code-flip,stack-flip,reg-flip,stuck-sensor,irq-storm"
    )
    p.add_argument("--rates", default="0,0.25,1,4")
    p.add_argument("--seeds", type=int, default=4)
    p.add_argument("--seconds", type=float, default=40.0)
    p.add_argument("--settle", type=float, default=10.0)
    p.add_argument("--jobs", type=int)
    p.add_argument(
        "--no-safety", action="store_true", help="naive firmware: skip sensor plausibility checks"
    )
    p.add_argument("--json")
    p.add_argument("--plot")
    p.set_defaults(fn=cmd_campaign)

    p = sub.add_parser("asm", help="assemble firmware, print stats / listing")
    p.add_argument("file", nargs="?")
    p.add_argument("--listing", action="store_true")
    p.add_argument("--symbols", action="store_true")
    p.set_defaults(fn=cmd_asm)

    p = sub.add_parser("disasm", help="disassemble the firmware image")
    p.add_argument("--firmware")
    p.add_argument("--start")
    p.add_argument("--count", type=int, default=64)
    p.set_defaults(fn=cmd_disasm)

    a = ap.parse_args(argv)
    return a.fn(a)
