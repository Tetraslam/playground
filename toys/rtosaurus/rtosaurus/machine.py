"""Machine: wires CPU + Bus + Plant + firmware image, samples a trace (owner: agent 1)."""

from __future__ import annotations

from pathlib import Path

from rtosaurus import isa
from rtosaurus.asm import Image, assemble_file
from rtosaurus.bus import Bus
from rtosaurus.cpu import CPU
from rtosaurus.plant import Plant

FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"
TASK_STATES = ["free", "ready", "running", "sleeping", "blk-send", "blk-recv", "dead"]
TCB_WORDS = 6
NUM_TCBS = 9


def build_firmware(path: Path | str = FIRMWARE / "main.s") -> Image:
    return assemble_file(str(path))


class Machine:
    """One emulated board. `sample_cycles` sets the trace resolution (default: every tick)."""

    def __init__(
        self,
        image: Image | None = None,
        seed: int = 0,
        plant: Plant | None = None,
        sample_cycles: int = 1000,
        trace_limit: int = 200_000,
        safety: bool = True,
        hw_watchdog: bool = True,
        account_tasks: bool = True,
    ):
        self.account_tasks = account_tasks  # exact per-task cycles (gantt); off = ~2x faster
        self.hw_watchdog = hw_watchdog  # watchdog can reset a halted CPU
        self.image = image if image is not None else build_firmware()
        self.seed = seed
        self.plant = plant if plant is not None else Plant(seed=seed)
        self.bus = Bus(self.plant, seed=seed)
        self.bus.load(self.image.words)
        if not safety:  # naive controller: firmware skips its sensor plausibility checks
            addr = self.image.symbols.get("app_cfg_safety")
            if addr is None:
                raise ValueError("firmware has no app_cfg_safety switch")
            self.bus.mem[addr] = 0
        self.safety = safety
        self.cpu = CPU(self.bus)
        self.cpu.reset()  # pc = mem[VEC_RESET], after the image is loaded
        self.sample_cycles = sample_cycles
        self.trace_limit = trace_limit
        self.trace: list[dict] = []
        self.events: list[str] = []  # pending, flushed into the next sample
        self.event_log: list[tuple[float, str]] = []  # (sim t, event), never trimmed
        self.hooks: list = []  # callables hook(machine, dt_seconds) run at each sample
        self._next_sample = 0
        self._uart_seen = 0
        self._uart_line = ""
        self.uart_lines: list[str] = []
        sym = self.image.symbols
        self._k_tcb = sym.get("k_tcb")
        self._k_current = sym.get("k_current")
        self._k_ticks = sym.get("k_ticks")
        self._task_cycles: dict[int, int] = {}
        self._halt_logged = False  # task id -> cycles since last sample

    # ---- time ----------------------------------------------------------
    @property
    def t(self) -> float:
        return self.bus.cycles / isa.CLOCK_HZ

    @property
    def halted(self) -> bool:
        return self.cpu.halted

    def step(self) -> int:
        if self.cpu.halted:
            return 0
        cur = self.current_task()
        c = self.cpu.step()
        self.bus.tick(c)
        if cur is not None:
            self._task_cycles[cur] = self._task_cycles.get(cur, 0) + c
        if self.bus.cycles >= self._next_sample:
            self._sample()
        return c

    def run(self, cycles: int) -> None:
        """Advance `cycles` cycles. If the CPU halts, the plant keeps running (outputs latched)."""
        end = self.bus.cycles + cycles
        while self.bus.cycles < end:
            self._run_live(end)
            if self.cpu.halted:
                self._run_halted(end)

    def _run_halted(self, end: int) -> None:
        """A dead CPU doesn't stop physics: PWM outputs stay latched and the plant keeps going.
        The watchdog is separate hardware, so if it was armed it still bites and
        resets the chip (like a real WDT reset). RAM survives a reset, as on silicon."""
        bus = self.bus
        while bus.cycles < end:
            bus.tick(min(self._next_sample, end) - bus.cycles)
            if self.hw_watchdog and bus.pending_nmi():
                self.hw_reset("wdog hw reset")
                return
            if bus.cycles >= self._next_sample:
                self._sample()

    def hw_reset(self, why: str = "hw reset") -> None:
        """Chip reset: actuators off, CPU back to the reset vector. RAM is kept."""
        bus = self.bus
        bus.ack_irq(isa.VEC_WDOG)
        for reg in (
            isa.MMIO_PWM_HEATER,
            isa.MMIO_PWM_FAN,
            isa.MMIO_TIMER_CTRL,
            isa.MMIO_WDOG_TIMEOUT,
        ):
            bus.write(reg, 0)
        self.cpu.reset()
        self._halt_logged = False
        self.event(why)

    def _run_live(self, end: int) -> None:
        cpu, bus = self.cpu, self.bus
        mem, kc, acc = bus.mem, self._k_current, self._task_cycles
        while bus.cycles < end and not cpu.halted:
            # inner loop without sampling checks, up to the next sample point
            stop = min(end, self._next_sample)
            if kc is None or not self.account_tasks:
                cpu.run(stop - bus.cycles)  # fast path: cpu ticks the bus itself
            else:  # also account cycles to the running task (exact gantt, no aliasing)
                while bus.cycles < stop and not cpu.halted:
                    cur = mem[kc]
                    c = cpu.step()
                    bus.tick(c)
                    acc[cur] = acc.get(cur, 0) + c
            if bus.cycles >= self._next_sample:
                self._sample()
        if cpu.halted:
            self._sample()  # record the halt event promptly

    def run_seconds(self, seconds: float) -> None:
        self.run(int(seconds * isa.CLOCK_HZ))

    # ---- host-side pokes -------------------------------------------------
    def send(self, text: str) -> None:
        """Type into the firmware's UART."""
        self.bus.uart_feed(text)
        self.event(f"uart> {text.strip()}")

    def set_setpoint(self, degc: float) -> None:
        self.plant.setpoint = degc
        self.event(f"knob {degc:g}C")

    def event(self, what: str) -> None:
        self.events.append(what)
        self.event_log.append((round(self.t, 4), what))

    # ---- introspection ---------------------------------------------------
    def peek(self, addr: int) -> int:
        return self.bus.mem[addr & 0xFFFF]

    def current_task(self) -> int | None:
        return None if self._k_current is None else self.bus.mem[self._k_current]

    def ticks(self) -> int | None:
        return None if self._k_ticks is None else self.bus.mem[self._k_ticks]

    def tasks(self) -> list[dict]:
        """Decoded kernel TCBs (only non-free slots)."""
        if self._k_tcb is None:
            return []
        mem = self.bus.mem
        cur = self.current_task()
        out = []
        for i in range(NUM_TCBS):
            b = self._k_tcb + i * TCB_WORDS
            state, prio, sp, wake, entry, faults = mem[b : b + TCB_WORDS]
            if state == 0:
                continue
            out.append(
                {
                    "id": i,
                    "name": self.symbol_at(entry) or f"0x{entry:04x}",
                    "state": TASK_STATES[state] if state < len(TASK_STATES) else f"?{state}",
                    "priority": prio,
                    "sp": sp,
                    "wake_tick": wake,
                    "entry": entry,
                    "faults": faults,
                    "current": i == cur,
                }
            )
        return out

    def symbol_at(self, addr: int) -> str | None:
        if not hasattr(self, "_rev"):
            self._rev = {}
            for name, a in self.image.symbols.items():
                if a in self.image.lines and a not in self._rev:
                    self._rev[a] = name
        return self._rev.get(addr)

    def uart_text(self) -> str:
        return "".join(self.bus.uart_out)

    # ---- trace -----------------------------------------------------------
    def _scan_uart(self) -> None:
        out = self.bus.uart_out
        n = len(out)
        if n == self._uart_seen:
            return
        chunk = "".join(out[self._uart_seen : n])
        self._uart_seen = n
        for ch in chunk:
            if ch == "\n":
                line = self._uart_line
                self.uart_lines.append(line)
                if line.startswith("!"):  # kernel diagnostics: !fault ..., !wdog
                    self.event(line[1:].strip())
                self._uart_line = ""
            else:
                self._uart_line += ch

    def _sample(self) -> None:
        self._next_sample = self.bus.cycles + self.sample_cycles
        self._scan_uart()
        dt = self.sample_cycles / isa.CLOCK_HZ
        for h in self.hooks:
            h(self, dt)
        pop = getattr(self.plant, "pop_events", None)
        if pop is not None:
            for e in pop():
                self.event(e)
        if self.cpu.halted and not self._halt_logged:
            self._halt_logged = True
            self.event("halt (double fault)" if self.cpu.double_fault else "halt")
        st = self.plant.state()
        self.trace.append(
            {
                "t": round(self.t, 4),
                "plant_t": st.get("t"),
                "temp": st.get("temp"),
                "setpoint": st.get("setpoint"),
                "heater": st.get("heater"),
                "fan": st.get("fan"),
                "ambient": st.get("ambient"),
                "door_open": st.get("door_open"),
                "task": self.current_task(),
                # every task that ran since the previous sample -> cycles it used
                "task_cycles": dict(sorted(self._task_cycles.items())),
                "events": self.events,
            }
        )
        self.events = []
        self._task_cycles.clear()  # in place: run() holds a reference
        if len(self.trace) > self.trace_limit:
            del self.trace[: len(self.trace) - self.trace_limit]

    def summary(self, warmup: float = 0.3) -> dict:
        """Run outcome. `warmup` = fraction of the trace ignored for tracking error."""
        temps = [s["temp"] for s in self.trace if s["temp"] is not None]
        tail = self.trace[int(len(self.trace) * warmup) :]
        errs = [abs(s["temp"] - s["setpoint"]) for s in tail if s["temp"] is not None]
        kinds = [e for _, e in self.event_log]
        st = self.plant.state()
        return {
            "t": round(self.t, 3),
            "boiled": bool(st.get("boiled")) or (max(temps, default=0) >= 100),
            "max_temp": round(max(temps, default=float("nan")), 2),
            "final_temp": round(st.get("temp", float("nan")), 2),
            "mean_abs_err": round(sum(errs) / len(errs), 3) if errs else None,
            "halted": self.cpu.halted,
            "double_fault": self.cpu.double_fault,
            "task_faults": sum(k.startswith("fault") for k in kinds),
            "wdog_resets": sum(k.startswith("wdog") for k in kinds),
            "halts": sum(k.startswith("halt") for k in kinds),
            "injections": sum(k.startswith("inject") for k in kinds),
        }
