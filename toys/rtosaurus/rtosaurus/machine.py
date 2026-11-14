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
    ):
        self.image = image if image is not None else build_firmware()
        self.seed = seed
        self.plant = plant if plant is not None else Plant(seed=seed)
        self.bus = Bus(self.plant, seed=seed)
        self.bus.load(self.image.words)
        self.cpu = CPU(self.bus)
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
        c = self.cpu.step()
        self.bus.tick(c)
        if self.bus.cycles >= self._next_sample:
            self._sample()
        return c

    def run(self, cycles: int) -> None:
        """Run for `cycles` more cycles (or until halt)."""
        end = self.bus.cycles + cycles
        cpu, bus = self.cpu, self.bus
        while bus.cycles < end and not cpu.halted:
            # inner loop without sampling checks, up to the next sample point
            stop = min(end, self._next_sample)
            while bus.cycles < stop and not cpu.halted:
                bus.tick(cpu.step())
            if bus.cycles >= self._next_sample:
                self._sample()
        if cpu.halted:
            self._sample()

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
        if self.cpu.halted and not any(e.startswith("halt") for _, e in self.event_log[-3:]):
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
                "events": self.events,
            }
        )
        self.events = []
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
            "injections": sum(k.startswith("inject") for k in kinds),
        }
