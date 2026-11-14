"""Live terminal dashboard for a running T16 machine (owner: agent 8).

    uv run python -m rtosaurus dash            # via the CLI (agent 1)
    uv run python -m rtosaurus.dash [--seed N] # standalone

Panels: tank chart (temp vs setpoint, braille), plant gauges, LEDs, RTOS task
table, CPU registers + disassembly around pc, UART console, event log.

Keys: p/space pause, +/- (or up/down) setpoint +-1 C (shift+arrow: 5),
[ ] slower/faster, f inject a random fault, 1-6 a specific one (faults.KINDS:
data-flip, code-flip, stack-flip, reg-flip, stuck-sensor, irq-storm), z/x/c/v press buttons 0-3,
/ or u type into the UART (enter sends, esc leaves), q quit.

The dashboard only *reads* the machine through the PLAN.md contract
(`Machine.run`, `.tasks()`, `.trace`, `.uart_text()`, `.bus`, `.cpu`, `.plant`,
`.image`) and pokes it the way a user at the bench would (setpoint knob, UART,
buttons, faults). Simulation runs on the UI thread in small cycle chunks with
a per-frame time budget, so the UI never stalls even when Python can't keep up
with real time; the header shows the achieved speed.
"""

from __future__ import annotations

import random
import time
from collections import deque

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Input, RichLog, Static

from . import isa

FPS = 20
FRAME_BUDGET = 0.035  # seconds of CPU per frame we're willing to spend simulating
CHUNK = 1000  # cycles per machine.run() call (one RTOS tick)
SPEEDS = [0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 64.0]
STATES = {0: "free", 1: "ready", 2: "RUN", 3: "sleep", 4: "send", 5: "recv", 6: "DEAD"}
STATE_ALIAS = {
    "running": "RUN",
    "sleeping": "sleep",
    "blk-send": "send",
    "blk-recv": "recv",
    "dead": "DEAD",
}
STATE_STYLE = {
    "RUN": "bold #e0b04a",
    "DEAD": "bold #d0533f",
    "ready": "#7fb069",
    "sleep": "#6aa0c8",
    "send": "#c08fd0",
    "recv": "#c08fd0",
    "free": "#5a5048",
}
try:
    from .faults import KINDS as FAULT_KINDS  # keys 1..N
except Exception:  # pragma: no cover
    FAULT_KINDS = ["data-flip", "code-flip", "stack-flip", "reg-flip", "stuck-sensor", "irq-storm"]
CPU_WINDOW = 100  # trace samples (= ticks) averaged for the cpu% column
FLAG_NAMES = [
    (isa.FLAG_I, "I"),
    (isa.FLAG_V, "V"),
    (isa.FLAG_C, "C"),
    (isa.FLAG_N, "N"),
    (isa.FLAG_Z, "Z"),
]
BRAILLE = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]  # [row][col] dot bits


# ----------------------------------------------------------------------------- helpers


def braille_chart(
    series: list[tuple[list[float], str]],
    width: int,
    height: int,
    lo: float,
    hi: float,
    hlines: list[tuple[float, str]] = (),
) -> list[Text]:
    """Render line series into `height` rows of braille, 2x4 dots per cell.

    Each series is (values, style); later series win a cell's colour. Values are
    right-aligned: the newest sample is the rightmost dot column.
    """
    W, H = width * 2, height * 4
    bits = [[0] * width for _ in range(height)]
    style = [[""] * width for _ in range(height)]

    def ydot(v):
        f = (v - lo) / (hi - lo) if hi > lo else 0.5
        return min(H - 1, max(0, round((1 - f) * (H - 1))))

    def plot(x, y, st):
        r, c = y // 4, x // 2
        bits[r][c] |= BRAILLE[y % 4][x % 2]
        style[r][c] = st

    for v, st in hlines:
        y = ydot(v)
        for x in range(0, W, 3):
            plot(x, y, st)
    for vals, st in series:
        vals = vals[-W:]
        off = W - len(vals)
        prev = None
        for k, v in enumerate(vals):
            if v is None:
                prev = None
                continue
            x, y = off + k, ydot(v)
            if prev is not None:  # fill vertical gaps so steep edges stay connected
                for yy in range(min(prev, y) + 1, max(prev, y)):
                    plot(x, yy, st)
            plot(x, y, st)
            prev = y
    rows = []
    for r in range(height):
        t = Text()
        for c in range(width):
            t.append(chr(0x2800 + bits[r][c]) if bits[r][c] else " ", style[r][c] or None)
        rows.append(t)
    return rows


def bar(frac: float, width: int, style: str) -> Text:
    frac = min(1.0, max(0.0, frac))
    full = frac * width
    n = int(full)
    parts = " ▏▎▍▌▋▊▉"
    s = "█" * n + (parts[int((full - n) * 8)] if n < width else "")
    t = Text(s.ljust(width), style=style)
    t.stylize("on #2a231d")
    return t


def fmt_q88(v: int) -> str:
    v &= 0xFFFF
    v = v - 0x10000 if v & 0x8000 else v
    return f"{v / 256:.2f}"


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _fallback_disasm(w0: int, w1: int, symbols=None) -> str:
    name, rd, rs, imm = isa.decode(w0, w1)
    return f"{name or '???'} r{rd}, r{rs}, {imm:#06x}" if name else f".word {w0:#06x}, {w1:#06x}"


try:
    from .disasm import disasm as _disasm
except Exception:  # disasm.py not landed / broken: degrade, don't die
    _disasm = _fallback_disasm


# ----------------------------------------------------------------------------- widgets


class Chart(Static):
    """Tank temperature (orange) vs setpoint (cyan) and heater duty (red, scaled)."""

    def __init__(self, dash: Dash, **kw):
        super().__init__(**kw)
        self.dash = dash

    def render(self):
        w = max(10, self.size.width - 6)
        h = max(3, self.size.height - 1)
        d = self.dash
        lo, hi = 0.0, 105.0
        temps = list(d.h_temp)
        rows = braille_chart(
            [
                (
                    [None if x is None else x * 15 for x in d.h_heat],
                    "#7a2e22",
                ),  # heater as a 0-15 band
                (list(d.h_set), "#6aa0c8"),
                (temps, "bold #e0913a"),
            ],
            w,
            h,
            lo,
            hi,
            hlines=[(100.0, "#d0533f"), (90.0, "#5a3a30")],
        )
        out = Text()
        for r, row in enumerate(rows):
            v = hi - (hi - lo) * r / max(1, h - 1)
            label = f"{v:>4.0f} " if r % 2 == 0 else "     "
            out.append(label, "#6b5f50")
            out.append_text(row)
            out.append("\n")
        out.append("     ", None)
        out.append("━ temp ", "#e0913a")
        out.append("━ setpoint ", "#6aa0c8")
        out.append("━ heater duty (0-15 band) ", "#7a2e22")
        out.append("┄ boil", "#d0533f")
        return out


# ----------------------------------------------------------------------------- app


class Dash(App):
    TITLE = "rtosaurus"
    CSS = """
    Screen { background: #14110f; color: #e8dcc8; }
    #status { height: 1; background: #1d1916; color: #e8dcc8; padding: 0 1; }
    #top { height: 1fr; }
    #bottom { height: 14; }
    .box { border: round #3a322b; border-title-color: #e0b04a; background: #14110f; height: 100%; }
    #chart { width: 2fr; }
    #gauges { width: 1fr; min-width: 34; }
    #tasks { width: 1fr; min-width: 52; }
    #cpu { width: 1fr; min-width: 40; }
    #uartcol { width: 1fr; }
    #uart { height: 1fr; }
    #uin { height: 3; border: round #3a322b; background: #14110f; }
    #uin:focus { border: round #e0b04a; }
    #events { width: 1fr; }
    DataTable { background: #14110f; }
    DataTable > .datatable--header { background: #1d1916; color: #8a7d6a; }
    DataTable > .datatable--cursor { background: #14110f; }
    #mid { height: 15; }
    """
    BINDINGS = [
        Binding("p,space", "pause", "pause"),
        Binding("plus,equals_sign,up", "setpoint(1)", "set+"),
        Binding("minus,down", "setpoint(-1)", "set-"),
        Binding("shift+up", "setpoint(5)", show=False),
        Binding("shift+down", "setpoint(-5)", show=False),
        Binding("left_square_bracket", "slower", "slower"),
        Binding("right_square_bracket", "faster", "faster"),
        Binding("f", "fault('')", "fault!"),
        *[
            Binding(str(k + 1), f"fault('{kind}')", kind, show=False)
            for k, kind in enumerate(FAULT_KINDS)
        ],
        *[Binding(key, f"button({b})", f"btn{b}", show=False) for b, key in enumerate("zxcv")],
        Binding("slash,u", "uart_focus", "uart"),
        Binding("escape", "uart_blur", show=False),
        Binding("q", "quit", "quit"),
        Binding("ctrl+q", "quit", show=False, priority=True),
    ]

    def __init__(self, machine, *, speed: float = 1.0, seed: int = 0, autorun: bool = True):
        super().__init__()
        self.m = machine
        self.speed_i = min(range(len(SPEEDS)), key=lambda k: abs(SPEEDS[k] - speed))
        self.paused = False
        self.autorun = autorun
        self.rng = random.Random(seed)
        n = 600
        self.h_temp: deque = deque(maxlen=n)
        self.h_set: deque = deque(maxlen=n)
        self.h_heat: deque = deque(maxlen=n)
        # prefill the chart from whatever the machine already ran (one point per frame's worth of cycles)
        stride = max(1, round(isa.CLOCK_HZ / FPS / max(1, getattr(machine, "sample_cycles", 1000))))
        for s in (safe(lambda: list(machine.trace), []) or [])[::-1][::stride][::-1][-n:]:
            self.h_temp.append(s.get("temp"))
            self.h_set.append(s.get("setpoint"))
            self.h_heat.append(s.get("heater"))
        self.uart_seen = 0
        self.uart_partial = ""
        self.trace_seen = 0
        self.achieved: float | None = None  # measured sim/real ratio, None until 0.5 s of wall time
        self._wall = time.perf_counter()
        self._cyc0 = self.cycles()
        self.sym_by_addr = {}
        img = getattr(machine, "image", None)
        for name, addr in sorted((getattr(img, "symbols", None) or {}).items()):
            self.sym_by_addr.setdefault(addr, name)
        self.events_count = 0

    # ---- layout

    def compose(self) -> ComposeResult:
        yield Static(id="status")
        with Horizontal(id="top"):
            c = Chart(self, id="chart", classes="box")
            c.border_title = "tank"
            yield c
            g = Static(id="gauges", classes="box")
            g.border_title = "plant / panel"
            yield g
        with Horizontal(id="mid"):
            t = DataTable(id="tasks", classes="box", cursor_type="none", zebra_stripes=False)
            t.border_title = "rtos tasks"
            yield t
            cpu = Static(id="cpu", classes="box")
            cpu.border_title = "cpu"
            yield cpu
        with Horizontal(id="bottom"):
            with Vertical(id="uartcol"):
                u = RichLog(id="uart", classes="box", max_lines=500, wrap=False, markup=False)
                u.border_title = "uart"
                yield u
                yield Input(placeholder="/ to type: s45 (setpoint)  p (tasks)  ? (help)", id="uin")
            e = RichLog(id="events", classes="box", max_lines=500, markup=False)
            e.border_title = "events"
            yield e
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#tasks", DataTable)
        for col in ("id", "task", "state", "pri", "cpu%", "sp", "wake", "flt"):
            t.add_column(col, key=col)
        self.query_one("#uin", Input).can_focus = True
        self.set_focus(None)
        if self.autorun:
            self.set_interval(1 / FPS, self.frame)
        self.refresh_views()

    # ---- sim

    def cycles(self) -> int:
        return safe(lambda: int(self.m.bus.cycles), 0)

    def halted(self) -> bool:
        return bool(safe(lambda: self.m.cpu.halted, False))

    def frame(self) -> None:
        if not self.paused:  # after a CPU halt the machine still advances the plant
            target = int(isa.CLOCK_HZ * SPEEDS[self.speed_i] / FPS)
            t0 = time.perf_counter()
            done = 0
            while done < target and time.perf_counter() - t0 < FRAME_BUDGET:
                n = min(CHUNK, target - done)
                try:
                    self.m.run(n)
                except Exception as e:  # never let a sim bug kill the UI
                    self.log_event(f"sim error: {type(e).__name__}: {e}", "bold #d0533f")
                    self.paused = True
                    break
                done += n
        now = time.perf_counter()
        if now - self._wall >= 0.5:
            c = self.cycles()
            self.achieved = (c - self._cyc0) / isa.CLOCK_HZ / (now - self._wall)
            self._wall, self._cyc0 = now, c
        self.sample()
        self.refresh_views()

    def sample(self) -> None:
        st = safe(lambda: self.m.plant.state(), {}) or {}
        self.h_temp.append(st.get("temp"))
        self.h_set.append(st.get("setpoint"))
        self.h_heat.append(st.get("heater"))

    # ---- views

    def refresh_views(self) -> None:
        self.update_status()
        self.query_one("#chart", Chart).refresh()
        self.update_gauges()
        self.update_tasks()
        self.update_cpu()
        self.pump_uart()
        self.pump_events()

    def update_status(self) -> None:
        c = self.cycles()
        st = safe(lambda: self.m.plant.state(), {}) or {}
        t = Text()
        t.append(" RTOSAURUS ", "bold #14110f on #e0b04a")
        t.append(f"  sim {c / isa.CLOCK_HZ:8.2f}s", "#e8dcc8")
        if "t" in st or "plant_t" in st:
            pt = st.get("t", st.get("plant_t", 0.0))
            t.append(f"  plant {pt / 60:6.1f}min", "#8a7d6a")
        t.append(f"  cyc {c:,}", "#8a7d6a")
        ticks = (
            safe(lambda: self.m.ticks()) if hasattr(self.m, "ticks") else self.sym_word("k_ticks")
        )
        if ticks is not None:
            t.append(f"  tick {ticks}", "#8a7d6a")
        t.append(f"  speed x{SPEEDS[self.speed_i]:g}", "#e8dcc8")
        if self.achieved is not None and not self.paused:
            t.append(f" (got x{self.achieved:.2f})", "#6b5f50")
        if self.halted():
            df = safe(lambda: self.m.cpu.double_fault, False)
            t.append("  ■ DOUBLE FAULT" if df else "  ■ HALTED", "bold #d0533f")
        elif self.paused:
            t.append("  ❚❚ paused", "bold #d9913a")
        else:
            t.append("  ▶ running", "#7fb069")
        if st.get("boiled"):
            t.append("  ☠ BOILED", "bold #ffffff on #d0533f")
        self.query_one("#status", Static).update(t)

    def update_gauges(self) -> None:
        st = safe(lambda: self.m.plant.state(), {}) or {}
        w = max(10, self.query_one("#gauges").size.width - 14)
        t = Text()
        temp, sp = st.get("temp"), st.get("setpoint")
        if temp is not None:
            hot = "bold #d0533f" if temp >= 90 else "bold #e0913a"
            t.append("tank     ", "#8a7d6a")
            t.append(f"{temp:6.2f} °C\n", hot)
        if sp is not None:
            t.append("setpoint ", "#8a7d6a")
            t.append(f"{sp:6.2f} °C", "#6aa0c8")
            if temp is not None:
                err = temp - sp
                t.append(f"  {err:+.2f}\n", "#7fb069" if abs(err) < 1 else "#d9913a")
            else:
                t.append("\n")
        amb = st.get("ambient")
        if amb is not None:
            t.append("ambient  ", "#8a7d6a")
            t.append(f"{amb:6.2f} °C\n", "#b8a98f")
        t.append("\nheater ", "#8a7d6a")
        t.append_text(bar(st.get("heater", 0.0) or 0.0, w, "#d0533f"))
        t.append(f" {round((st.get('heater') or 0) * 255):3d}\n")
        t.append("fan    ", "#8a7d6a")
        t.append_text(bar(st.get("fan", 0.0) or 0.0, w, "#6aa0c8"))
        t.append(f" {round((st.get('fan') or 0) * 255):3d}\n")
        if "door_open" in st:
            t.append("door   ", "#8a7d6a")
            t.append(
                "OPEN\n" if st["door_open"] else "shut\n",
                "bold #d9913a" if st["door_open"] else "#5a5048",
            )
        ov = safe(lambda: self.m.plant.sensor_override)
        if ov is not None:
            t.append("sensor ", "#8a7d6a")
            t.append(f"STUCK at {ov:.1f} °C\n", "bold #d0533f")
        t.append("\nleds   ", "#8a7d6a")
        leds = self.peek(isa.MMIO_GPIO_OUT) or 0
        for k in range(8):
            on = leds >> k & 1
            col = ("#d0533f" if k == 7 else "#7fb069") if on else "#2a231d"
            t.append("● ", col)
        t.append("\n       0 1 2 3 4 5 6 7\n", "#5a5048")
        wd = self.peek(isa.MMIO_WDOG_TIMEOUT)
        if wd:
            t.append(f"\nwatchdog {wd * 256 / isa.CLOCK_HZ:.2f}s timeout\n", "#8a7d6a")
        self.query_one("#gauges", Static).update(t)

    def update_tasks(self) -> None:
        tbl = self.query_one("#tasks", DataTable)
        tasks = safe(lambda: self.m.tasks(), []) or []
        cur = safe(lambda: self.m.current_task())
        share = self.cpu_share()
        tbl.clear()
        for k, tk in enumerate(tasks):
            idx = tk.get("id", tk.get("index", k))
            state = tk.get("state", 0)
            sname = state if isinstance(state, str) else STATES.get(state, str(state))
            sname = STATE_ALIAS.get(sname, sname)
            if sname == "free":
                continue
            if (tk.get("current") or (cur is not None and idx == cur)) and sname != "DEAD":
                sname = "RUN"
            name = (
                tk.get("name")
                or self.sym_by_addr.get(tk.get("entry"), "")
                or ("idle" if idx == 8 else f"{tk.get('entry', 0):#06x}")
            )
            sty = STATE_STYLE.get(sname, "")
            faults = tk.get("faults", 0)
            tbl.add_row(
                Text(str(idx), sty),
                Text(str(name)[:16], sty),
                Text(sname, sty),
                str(tk.get("priority", "")),
                Text(f"{share[idx] * 100:5.1f}" if idx in share else "    -", "#b8a98f"),
                f"{tk.get('sp', tk.get('saved_sp', 0)):#06x}",
                str(tk.get("wake_tick", "")),
                Text(str(faults), "bold #d0533f" if faults else "#5a5048"),
            )

    def cpu_share(self) -> dict[int, float]:
        """Fraction of cycles each task got over the last CPU_WINDOW trace samples."""
        trace = safe(lambda: self.m.trace[-CPU_WINDOW:], []) or []
        acc: dict[int, int] = {}
        for s in trace:
            for tid, c in (s.get("task_cycles") or {}).items():
                acc[int(tid)] = acc.get(int(tid), 0) + c
        total = sum(acc.values())
        return {t: c / total for t, c in acc.items()} if total else {}

    def update_cpu(self) -> None:
        cpu = getattr(self.m, "cpu", None)
        if cpu is None:
            return
        regs = safe(lambda: list(cpu.regs), [0] * 8)
        pc = safe(lambda: int(cpu.pc), 0)
        flags = safe(lambda: int(cpu.flags), 0)
        t = Text()
        for k in range(8):
            nm = "sp" if k == isa.SP else f"r{k}"
            t.append(f"{nm:>3} ", "#8a7d6a")
            t.append(f"{regs[k] & 0xFFFF:04x}", "#e8dcc8")
            t.append("   " if k % 4 != 3 else "\n")
        t.append(" pc ", "#8a7d6a")
        t.append(f"{pc:04x}  ", "bold #e0b04a")
        for bit, ch in FLAG_NAMES:
            t.append(ch, "bold #7fb069" if flags & bit else "#3a322b")
        sym = self.nearest_symbol(pc)
        if sym:
            t.append(f"  {sym}", "#6aa0c8")
        t.append("\n\n")
        h = max(3, self.query_one("#cpu").size.height - 6)
        width = max(20, self.query_one("#cpu").size.width - 4)
        lines = safe(lambda: self.m.image.lines, {}) or {}
        syms = safe(lambda: self.m.image.symbols)
        start = pc - 2 * (h // 3)
        for k in range(h):
            a = (start + 2 * k) & 0xFFFF
            w0 = self.mem(a)
            w1 = self.mem(a + 1)
            if w0 is None:
                break
            dis = safe(lambda w0=w0, w1=w1: _disasm(w0, w1, syms), None) or _fallback_disasm(w0, w1)
            here = a == pc
            lab = self.sym_by_addr.get(a)
            t.append("▶ " if here else "  ", "bold #e0b04a")
            t.append(f"{a:04x} ", "#e0b04a" if here else "#5a5048")
            line = f"{dis}"
            if lab:
                line = f"{lab}: {line}"
            src = lines.get(a)
            if src and len(line) < width - 20:
                where, _, code = src.partition(" ")
                where = where.rsplit("/", 1)[-1]
                line = f"{line:<24}; {where}"
            t.append(line[: width - 7] + "\n", "bold #e8dcc8" if here else "#b8a98f")
        self.query_one("#cpu", Static).update(t)

    def pump_uart(self) -> None:
        text = safe(lambda: self.m.uart_text(), None)
        if text is None:
            text = "".join(safe(lambda: self.m.bus.uart_out, []) or [])
        if len(text) < self.uart_seen:  # machine was replaced/reset
            self.uart_seen = 0
        new = text[self.uart_seen :]
        self.uart_seen = len(text)
        if not new:
            return
        log = self.query_one("#uart", RichLog)
        buf = self.uart_partial + new
        *done, self.uart_partial = buf.split("\n")
        for line in done:
            line = line.rstrip("\r")
            log.write(Text(line, "bold #d0533f" if line.startswith("!") else "#e8dcc8"))

    def pump_events(self) -> None:
        """Machine.event_log (faults, wdog, injections, knob, uart>) -> events pane."""
        evs = safe(lambda: self.m.event_log, None)
        if evs is None:  # older machine: fall back to per-sample trace events
            evs = [
                (s.get("t", 0.0), e)
                for s in (safe(lambda: self.m.trace, []) or [])
                for e in s.get("events") or []
            ]
        if len(evs) < self.trace_seen:
            self.trace_seen = 0
        for t, ev in evs[self.trace_seen :]:
            if ev.startswith(("fault", "wdog", "halt", "boil")):
                sty = "bold #d0533f"
            elif ev.startswith("inject"):
                sty = "bold #d9913a"
            elif ev.startswith(("knob", "uart>", "button")):
                sty = "#6aa0c8"
            else:
                sty = "#b8a98f"
            self.log_event(f"{t:8.2f}s  {ev}", sty)
        self.trace_seen = len(evs)

    def log_event(self, msg: str, style: str = "#e8dcc8") -> None:
        self.events_count += 1
        self.query_one("#events", RichLog).write(Text(msg, style))

    # ---- memory helpers (never touch side-effecting MMIO except the ones we name)

    def mem(self, addr: int) -> int | None:
        if addr >= isa.MMIO_BASE:
            return None
        return safe(lambda: self.m.bus.mem[addr] & 0xFFFF)

    def peek(self, mmio: int) -> int | None:
        return safe(lambda: self.m.bus.read(mmio) & 0xFFFF)

    def sym_word(self, name: str) -> int | None:
        addr = safe(lambda: self.m.image.symbols[name])
        return None if addr is None else self.mem(addr)

    def nearest_symbol(self, pc: int) -> str:
        best = None
        for a, n in self.sym_by_addr.items():
            if a <= pc and (best is None or a > best[0]) and not n.isupper():
                best = (a, n)
        if not best:
            return ""
        return best[1] if best[0] == pc else f"{best[1]}+{pc - best[0]}"

    # ---- actions

    def action_pause(self) -> None:
        self.paused = not self.paused

    def action_slower(self) -> None:
        self.speed_i = max(0, self.speed_i - 1)

    def action_faster(self) -> None:
        self.speed_i = min(len(SPEEDS) - 1, self.speed_i + 1)

    def action_setpoint(self, delta: float) -> None:
        plant = getattr(self.m, "plant", None)
        if plant is None:
            return
        new = round(min(99.0, max(0.0, plant.setpoint + delta)), 2)
        if hasattr(self.m, "set_setpoint"):
            self.m.set_setpoint(new)  # logs "knob NC" into event_log
        else:
            plant.setpoint = new
        self.refresh_views()

    def action_button(self, b: int) -> None:
        try:
            self.m.bus.press(b)
        except Exception as e:
            self.log_event(f"button {b} failed: {e}", "#d0533f")
            return
        if hasattr(self.m, "event"):
            self.m.event(f"button {b}")
        self.refresh_views()

    def action_fault(self, kind: str = "") -> None:
        kind = kind or self.rng.choice(FAULT_KINDS)
        try:
            from .faults import inject_now

            msg = inject_now(self.m, kind, self.rng)  # logs into machine.event_log itself
        except Exception as e:
            self.log_event(f"inject {kind} failed: {type(e).__name__}: {e}", "#d0533f")
            return
        if not msg:
            self.log_event(f"inject {kind}: nothing to do (already active)", "#8a7d6a")
        self.refresh_views()

    def action_uart_focus(self) -> None:
        self.query_one("#uin", Input).focus()

    def action_uart_blur(self) -> None:
        self.set_focus(None)

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        s = ev.value
        ev.input.value = ""
        try:
            if hasattr(self.m, "send"):
                self.m.send(s + "\n")
            else:
                self.m.bus.uart_feed(s + "\n")
        except Exception as e:
            self.log_event(f"uart feed failed: {e}", "#d0533f")
            return
        self.query_one("#uart", RichLog).write(Text(f"» {s}", "#6aa0c8"))
        self.refresh_views()


def run(machine=None, *, seed: int = 0, speed: float = 1.0) -> None:
    """Open the dashboard on `machine` (built from firmware/main.s if None)."""
    if machine is None:
        from .machine import Machine, build_firmware

        machine = Machine(build_firmware(), seed=seed)
    Dash(machine, speed=speed, seed=seed).run()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="rtosaurus live dashboard")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args()
    run(seed=a.seed, speed=a.speed)
