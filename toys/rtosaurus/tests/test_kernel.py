"""Kernel tests (agent 6): firmware/kernel.s with small purpose-built apps."""

from rtosaurus import isa
from rtosaurus.asm import assemble
from rtosaurus.machine import FIRMWARE, Machine

TICK = 1000  # cycles


def boot(app: str, seed: int = 0) -> Machine:
    src = f'.include "{FIRMWARE / "kernel.s"}"\n' + app
    img = assemble(src, path="<kernel-test>")
    m = Machine(image=img, seed=seed)
    m.cpu.reset()  # idempotent; guards against a CPU that doesn't reset in __init__
    return m


def word(m: Machine, sym: str, off: int = 0) -> int:
    return m.peek(m.image.symbols[sym] + off)


def tcb(m: Machine, i: int) -> list[int]:
    b = m.image.symbols["k_tcb"] + 6 * i
    return [m.peek(b + k) for k in range(6)]


def test_round_robin_and_ticks():
    m = boot(
        """
app_init: RET
task_table:
    .word spin_a, 1, 16
    .word spin_b, 1, 16
    .word 0
spin_a: LD r1, [cnt_a]
        ADDI r1, 1
        ST [cnt_a], r1
        JMP spin_a
spin_b: LD r1, [cnt_b]
        ADDI r1, 1
        ST [cnt_b], r1
        JMP spin_b
cnt_a: .word 0
cnt_b: .word 0
"""
    )
    m.run(100 * TICK)
    assert not m.halted
    assert m.uart_text().startswith("!boot\n")
    assert 98 <= m.ticks() <= 101
    a, b = word(m, "cnt_a"), word(m, "cnt_b")
    assert a > 1000 and b > 1000 and 0.8 < a / b < 1.25, (a, b)
    assert tcb(m, 8)[0] == 1  # idle never needed


def test_priority_sleep_queues():
    # producer (prio 1) sends 0..19 into q0; consumer (prio 2) sleeps then drains.
    # q0 holds 8, so the producer must block and be woken by recv.
    m = boot(
        """
app_init: RET
task_table:
    .word producer, 1, 16
    .word consumer, 2, 16
    .word ticker, 3, 16
    .word 0
producer:
        LDI r3, 0
p_loop: LDI r0, 4
        LDI r1, 0
        MOV r2, r3
        TRAP 0
        ADDI r3, 1
        CMPI r3, 20
        JLT p_loop
        RET                     ; return -> exit
consumer:
        LDI r0, 1
        LDI r1, 20
        TRAP 0                  ; sleep 20 ticks
        LDI r4, out
c_loop: LDI r0, 5
        LDI r1, 0
        TRAP 0
        ST [r4], r0
        ADDI r4, 1
        CMPI r4, out + 20
        JLT c_loop
        LDI r0, 7
        TRAP 0
        ST [my_id], r0
        LDI r0, 6
        TRAP 0
ticker:                         ; highest priority but mostly asleep
        LDI r0, 1
        LDI r1, 10
        TRAP 0
        LD r1, [beats]
        ADDI r1, 1
        ST [beats], r1
        LDI r0, 2
        TRAP 0
        ST [last_tick], r0
        JMP ticker
beats: .word 0
last_tick: .word 0
my_id: .word 0
out: .zero 20
"""
    )
    m.run(60 * TICK)
    assert not m.halted
    assert [word(m, "out", i) for i in range(20)] == list(range(20))
    assert word(m, "my_id") == 1
    assert tcb(m, 0)[0] == 6 and tcb(m, 1)[0] == 6  # both exited
    assert 5 <= word(m, "beats") <= 6
    assert abs(word(m, "last_tick") - m.ticks()) <= 10


def test_uart_rx_queue_and_putc():
    m = boot(
        """
app_init: RET
task_table:
    .word echo, 1, 16
    .word 0
echo:   LDI r0, 5
        LDI r1, 7
        TRAP 0
        MOV r1, r0
        ADDI r1, 'A' - 'a'      ; upper-case it
        LDI r0, 3
        TRAP 0
        JMP echo
"""
    )
    m.run(5 * TICK)
    assert tcb(m, 0)[0] == 5  # blocked on recv
    m.send("hello")
    m.run(5 * TICK)
    assert m.uart_text() == "!boot\nHELLO"


def test_uart_burst_larger_than_queue_is_not_dropped():
    m = boot(
        """
app_init: RET
task_table:
    .word echo, 1, 16
    .word 0
echo:   LDI r0, 5
        LDI r1, 7
        TRAP 0
        MOV r1, r0
        LDI r0, 3
        TRAP 0
        JMP echo
"""
    )
    m.run(3 * TICK)
    burst = "zz\ns\nkx3\ns52.5\nthe quick brown fox\n"
    m.send(burst)
    m.run(40 * TICK)
    assert m.uart_text() == "!boot\n" + burst
    assert word(m, "k_uart_drops") == 0


def test_fault_kills_only_the_faulting_task():
    m = boot(
        """
app_init: RET
task_table:
    .word good, 1, 16
    .word bad, 2, 16
    .word 0
good:   LD r1, [cnt]
        ADDI r1, 1
        ST [cnt], r1
        JMP good
bad:    LDI r0, 1
        LDI r1, 5
        TRAP 0
        LDI r1, 0
boom:   DIV r1, r1
        JMP bad
cnt: .word 0
"""
    )
    m.run(20 * TICK)
    boom = m.image.symbols["boom"]
    assert f"!fault t1 c11 pc{boom:04x}\n" in m.uart_text()
    assert tcb(m, 1)[0] == 6 and tcb(m, 1)[5] == 1
    before = word(m, "cnt")
    m.run(5 * TICK)
    assert word(m, "cnt") > before and not m.halted


def test_watchdog_restarts_firmware():
    m = boot(
        """
app_init:
        LDI r0, 50              ; 50*256 cycles ~ 0.13 s
        ST [MMIO_WDOG_TIMEOUT], r0
        RET
task_table:
    .word hog, 1, 16
    .word 0
hog:    JMP hog                 ; never kicks
"""
    )
    m.run(30 * TICK)
    out = m.uart_text()
    assert out.startswith("!boot\n!wdog\n!boot\n"), out
    assert word(m, "k_boots") >= 2


def test_corrupt_kernel_state_panics():
    m = boot(
        """
app_init: RET
task_table:
    .word idle_ish, 1, 16
    .word 0
idle_ish: JMP idle_ish
"""
    )
    m.run(3 * TICK)
    spin = m.image.symbols["idle_ish"]
    while m.cpu.pc != spin:  # poke while the task (not the kernel) runs
        m.step()
    m.bus.mem[m.image.symbols["k_current"]] = 0x1234
    m.run(3 * TICK)
    assert m.halted
    assert m.uart_text().endswith("!panic\n")


def test_real_firmware_boots():
    m = Machine(seed=1)
    m.cpu.reset()
    m.run(50 * TICK)
    assert not m.halted
    assert m.uart_text().startswith("!boot\n")
    assert isa.CLOCK_HZ // TICK == 100
