"""Dashboard tests against a fake machine (owner: agent 8).

The dash only touches the Machine contract, so a small fake drives every panel
and every key without needing firmware.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from rtosaurus import dash, isa


class FakeBus:
    def __init__(self):
        self.mem = [0] * 0x10000
        self.cycles = 0
        self.uart_out: list[str] = []
        self.fed: list[str] = []
        self.pressed: list[int] = []
        self.gpio = 0b1000_0001

    def read(self, addr):
        if addr == isa.MMIO_GPIO_OUT:
            return self.gpio
        if addr == isa.MMIO_WDOG_TIMEOUT:
            return 200
        return 0

    def uart_feed(self, s):
        self.fed.append(s)

    def press(self, b):
        self.pressed.append(b)


class FakePlant:
    def __init__(self):
        self.setpoint = 45.0
        self.temp = 20.0
        self.sensor_override = None

    def state(self):
        return {
            "t": 0.0,
            "temp": self.temp,
            "setpoint": self.setpoint,
            "ambient": 18.0,
            "heater": 0.6,
            "fan": 0.0,
            "door_open": False,
            "boiled": False,
        }


class FakeMachine:
    def __init__(self):
        self.bus = FakeBus()
        self.plant = FakePlant()
        # LDI r1, 42 ; JMP 0x10 at 0x10
        self.bus.mem[0x10], self.bus.mem[0x11] = isa.encode("LDI", 1, 0, 42)
        self.bus.mem[0x12], self.bus.mem[0x13] = isa.encode("JMP", 0, 0, 0x10)
        self.image = SimpleNamespace(
            words={0x10: 0, 0x11: 0, 0x12: 0, 0x13: 0},
            symbols={"ctl_task": 0x10, "k_ticks": 0x200},
            lines={0x10: "app.s:3  LDI r1, 42", 0x12: "app.s:4  JMP ctl_task"},
        )
        self.cpu = SimpleNamespace(
            regs=[0] * 8, pc=0x10, flags=isa.FLAG_I, halted=False, double_fault=False
        )
        self.event_log: list[tuple[float, str]] = []
        self.trace: list[dict] = []
        self.hooks: list = []
        self.sent: list[str] = []
        self.runs = 0

    @property
    def t(self):
        return self.bus.cycles / isa.CLOCK_HZ

    def run(self, n):
        self.runs += 1
        self.bus.cycles += n
        self.trace.append(
            {"t": self.t, "temp": self.plant.temp, "task_cycles": {0: 3 * n // 4, 8: n // 4}}
        )
        self.plant.temp = min(self.plant.setpoint, self.plant.temp + 0.5)
        self.cpu.regs[1] = 42
        if self.bus.cycles >= 3000 and not self.bus.uart_out:
            self.bus.uart_out.extend("T=20.50 S=45.00 H=150 F=0\n!fault t1 c11 pc0012\npart")

    def tasks(self):
        return [
            {
                "id": 0,
                "name": "ctl_task",
                "state": "running",
                "priority": 3,
                "sp": 0xEF00,
                "wake_tick": 0,
                "entry": 0x10,
                "faults": 0,
                "current": True,
            },
            {
                "id": 1,
                "name": "logger",
                "state": "dead",
                "priority": 2,
                "sp": 0xEE00,
                "wake_tick": 7,
                "entry": 0x40,
                "faults": 1,
                "current": False,
            },
            {
                "id": 8,
                "name": "idle",
                "state": "ready",
                "priority": 0,
                "sp": 0xED00,
                "wake_tick": 0,
                "entry": 0x80,
                "faults": 0,
                "current": False,
            },
        ]

    def current_task(self):
        return 0

    def ticks(self):
        return self.bus.cycles // 1000

    def uart_text(self):
        return "".join(self.bus.uart_out)

    def event(self, what):
        self.event_log.append((round(self.t, 4), what))

    def set_setpoint(self, c):
        self.plant.setpoint = c
        self.event(f"knob {c:g}C")

    def send(self, text):
        self.sent.append(text)
        self.bus.uart_feed(text)
        self.event(f"uart> {text.strip()}")


def _text(app, sel) -> str:
    w = app.query_one(sel)
    r = w.render()
    return getattr(r, "plain", str(r))


def _log_text(app, sel) -> str:
    return "\n".join(s.text for s in app.query_one(sel).lines)


def test_braille_chart_shapes():
    rows = dash.braille_chart([([0, 50, 100], "red")], width=4, height=2, lo=0, hi=100)
    assert len(rows) == 2 and all(len(r.plain) == 4 for r in rows)
    assert any(ch != " " for r in rows for ch in r.plain)


def test_dash_panels_and_keys():
    async def go():
        m = FakeMachine()
        app = dash.Dash(m, autorun=False)
        async with app.run_test(size=(160, 50)) as pilot:
            for _ in range(5):
                app.frame()
            await pilot.pause()
            assert m.runs > 0 and m.bus.cycles > 0
            status = _text(app, "#status")
            assert "running" in status and "tick" in status
            g = _text(app, "#gauges")
            assert "45.00" in g and "heater" in g and "watchdog" in g
            cpu = _text(app, "#cpu")
            assert "LDI" in cpu and "ctl_task" in cpu and "002a" in cpu
            tbl = app.query_one("#tasks")
            assert tbl.row_count == 3
            assert app.cpu_share() == {0: 0.75, 8: 0.25}
            uart = _log_text(app, "#uart")
            assert "T=20.50" in uart and "!fault" in uart and "part" not in uart

            await pilot.press("plus")
            assert m.plant.setpoint == 46.0
            await pilot.press("minus", "minus")
            assert m.plant.setpoint == 44.0
            assert any(e.startswith("knob 44") for _, e in m.event_log)

            await pilot.press("z")
            assert m.bus.pressed == [0]

            await pilot.press("p")
            assert app.paused
            before = m.runs
            app.frame()
            assert m.runs == before
            await pilot.press("p")
            assert not app.paused

            await pilot.press("6")  # irq-storm (faults.KINDS[5]) via faults.inject_now
            assert any(e.startswith("inject irq-storm") for _, e in m.event_log)
            assert m.bus.fed and len(m.hooks) == 1

            await pilot.press("slash")
            await pilot.press(*"s60")
            await pilot.press("enter")
            assert m.sent == ["s60\n"]
            await pilot.press("escape")

            app.frame()
            await pilot.pause()
            ev = _log_text(app, "#events")
            assert "knob 44" in ev and "inject irq-storm" in ev and "uart> s60" in ev

            m.cpu.halted = True
            before = m.runs
            app.frame()
            assert "HALTED" in _text(app, "#status")
            assert m.runs > before  # plant keeps running after a CPU halt
            await pilot.press("q")

    asyncio.run(go())
