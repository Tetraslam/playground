"""End-to-end: real firmware on the emulated board controlling the plant (owner: agent 1)."""

import pytest

pytest.importorskip("rtosaurus.asm")
pytest.importorskip("rtosaurus.bus")
pytest.importorskip("rtosaurus.plant")

from rtosaurus import isa  # noqa: E402
from rtosaurus.asm import assemble  # noqa: E402
from rtosaurus.faults import FaultSchedule, Injector, parse_spec  # noqa: E402
from rtosaurus.machine import FIRMWARE, Machine, build_firmware  # noqa: E402

HAVE_FW = all((FIRMWARE / f).exists() for f in ("kernel.s", "lib.s", "app.s"))
needs_fw = pytest.mark.skipif(not HAVE_FW, reason="firmware not landed yet")

TINY = """
.org 0
.word start, 0, 0, 0, 0, 0, 0
.org CODE_BASE
start:
    LDI r1, 'h'
    ST [MMIO_UART_TX], r1
    LDI r1, 'i'
    ST [MMIO_UART_TX], r1
    LDI r1, 10
    ST [MMIO_UART_TX], r1
    HALT
"""


def test_bare_metal_hello():
    m = Machine(assemble(TINY), seed=0)
    m.run(10_000)
    assert m.halted
    assert m.uart_text() == "hi\n"
    assert m.uart_lines == ["hi"]
    assert m.trace, "halt should still record a final sample"


def test_inject_now_logs_and_recovers():
    import random

    from rtosaurus.faults import inject_now

    m = Machine(assemble(TINY.replace("    HALT\n", "spin: JMP spin\n")), seed=0)
    msg = inject_now(m, "stuck-sensor", random.Random(1))
    assert msg and m.plant.sensor_override is not None
    assert m.event_log[-1][1] == msg
    m.run_seconds(9.0)
    assert m.plant.sensor_override is None
    assert any(e == "sensor recovered" for _, e in m.event_log)


def test_parse_spec():
    inj = parse_spec("data-flip:0.5,stuck-sensor")
    assert [(i.kind, i.rate) for i in inj] == [("data-flip", 0.5), ("stuck-sensor", 1.0)]
    with pytest.raises(ValueError):
        parse_spec("gremlins:3")


@pytest.fixture(scope="module")
def fw():
    return build_firmware()


@needs_fw
def test_firmware_assembles(fw):
    for sym in ("reset", "k_tcb", "k_current", "k_ticks", "task_table", "app_init"):
        assert sym in fw.symbols, sym
    assert fw.words[isa.VEC_RESET] == fw.symbols["reset"]


@needs_fw
def test_scheduler_runs_tasks(fw):
    m = Machine(fw, seed=1)
    m.run_seconds(2.0)
    assert not m.halted, m.uart_text()[-400:]
    assert m.ticks() and m.ticks() >= 150, "100 Hz tick should be running"
    ran = {s["task"] for s in m.trace}
    assert len(ran - {None}) >= 2, f"expected several tasks to run, saw {ran}"
    names = [t["name"] for t in m.tasks()]
    assert len(names) >= 3, names


@needs_fw
def test_controls_the_tank(fw):
    m = Machine(fw, seed=2)
    m.plant.setpoint = 45.0
    m.run_seconds(40.0)
    s = m.summary()
    assert not s["boiled"] and not s["halted"], s
    assert abs(s["final_temp"] - 45.0) < 4.0, s
    assert any(line.startswith("T=") for line in m.uart_lines), m.uart_lines[-5:]


@needs_fw
def test_shell_sets_setpoint(fw):
    m = Machine(fw, seed=3)
    m.run_seconds(1.0)
    m.send("s60\n")
    m.run_seconds(1.0)
    assert abs(m.plant.setpoint - 60.0) < 0.5, m.uart_lines[-5:]


@needs_fw
def test_faults_are_survivable_and_deterministic(fw):
    def go():
        m = Machine(fw, seed=4, sample_cycles=2000)
        m.hooks.append(FaultSchedule([Injector("irq-storm", 2.0), Injector("reg-flip", 0.5)], seed=4, start=1.0))
        m.run_seconds(6.0)
        return m.event_log, m.summary()

    a, b = go(), go()
    assert a == b, "same seed must replay exactly"
    assert a[1]["injections"] > 0


@needs_fw
def test_hw_watchdog_revives_a_halted_cpu(fw):
    m = Machine(fw, seed=5)
    m.run_seconds(3.0)
    m.cpu.halted = True  # e.g. a corrupted return address landed on HALT
    m.run_seconds(2.0)
    kinds = [e for _, e in m.event_log]
    assert "halt" in kinds and "wdog hw reset" in kinds
    assert not m.halted and kinds.count("boot") == 2

    dead = Machine(fw, seed=5, hw_watchdog=False)
    dead.run_seconds(3.0)
    dead.cpu.halted = True
    dead.run_seconds(2.0)
    assert dead.halted
