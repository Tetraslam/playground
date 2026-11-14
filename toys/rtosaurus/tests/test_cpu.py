"""CPU tests against a minimal fake bus (owner: agent 2). Independent of bus.py."""

import pytest
from rtosaurus import isa
from rtosaurus.cpu import CPU, BusError

E = isa.encode


class FakeBus:
    def __init__(self):
        self.mem = [0] * 0x10000
        self.cause = 0
        self.traparg = 0
        self.faultpc = 0
        self.halt_requested = False
        self.irqs: set[int] = set()
        self.readonly: set[int] = set()

    def read(self, addr):
        if addr >= isa.MMIO_BASE:
            raise BusError(addr, False)
        return self.mem[addr]

    def write(self, addr, val):
        if addr >= isa.MMIO_BASE or addr in self.readonly:
            raise BusError(addr, True)
        self.mem[addr] = val & 0xFFFF

    def pending_irq(self):
        return min(self.irqs) if self.irqs else None

    def ack_irq(self, vec):
        self.irqs.discard(vec)


def machine(*prog, sp=0x8000, vectors=None):
    """Load (op, rd, rs, imm) tuples at CODE_BASE; vectors: {vec: addr}."""
    bus = FakeBus()
    bus.mem[isa.VEC_RESET] = isa.CODE_BASE
    for v, addr in (vectors or {}).items():
        bus.mem[v] = addr
    addr = isa.CODE_BASE
    for ins in prog:
        w0, w1 = E(*ins)
        bus.mem[addr], bus.mem[addr + 1] = w0, w1
        addr += 2
    cpu = CPU(bus)
    cpu.reset()
    cpu.regs[isa.SP] = sp
    return cpu, bus


def run(cpu, n):
    return sum(cpu.step() for _ in range(n))


def F(cpu):
    f = cpu.flags
    return {k: bool(f & getattr(isa, f"FLAG_{k}")) for k in "ZNCV"}


def test_reset_and_ldi_mov():
    cpu, _ = machine(("LDI", 1, 0, 1234), ("MOV", 2, 1), ("HALT",))
    assert cpu.pc == isa.CODE_BASE
    run(cpu, 3)
    assert cpu.regs[2] == 1234 and cpu.halted
    assert cpu.step() == 1 and cpu.pc == isa.CODE_BASE + 6  # halted: no progress


def test_add_carry_overflow():
    cpu, _ = machine(("LDI", 1, 0, 0x7FFF), ("LDI", 2, 0, 1), ("ADD", 1, 2))
    run(cpu, 3)
    assert cpu.regs[1] == 0x8000 and F(cpu) == {"Z": False, "N": True, "C": False, "V": True}
    cpu, _ = machine(("LDI", 1, 0, 0xFFFF), ("ADDI", 1, 0, 1))
    run(cpu, 2)
    assert cpu.regs[1] == 0 and F(cpu) == {"Z": True, "N": False, "C": True, "V": False}


def test_sub_cmp_borrow_and_signed_jumps():
    # 3 - 5 = -2: borrow, negative, JLT taken
    cpu, _ = machine(
        ("LDI", 1, 0, 3),
        ("CMPI", 1, 0, 5),
        ("JLT", 0, 0, 0x100),
    )
    run(cpu, 2)
    assert cpu.regs[1] == 3 and F(cpu)["C"] and F(cpu)["N"] and not F(cpu)["V"]
    run(cpu, 1)
    assert cpu.pc == 0x100
    # -32768 - 1 overflows: N=0, V=1 -> still signed less-than
    cpu, _ = machine(("LDI", 1, 0, 0x8000), ("CMPI", 1, 0, 1), ("JLT", 0, 0, 0x200))
    run(cpu, 3)
    assert F(cpu)["V"] and cpu.pc == 0x200


@pytest.mark.parametrize(
    "a,b,taken",
    [
        (5, 5, {"JZ", "JGE", "JLE", "JNC", "JMP"}),
        (7, 5, {"JNZ", "JGE", "JGT", "JNC", "JMP"}),
        (5, 7, {"JNZ", "JLT", "JLE", "JC", "JMP"}),
        (0xFFFF, 1, {"JNZ", "JLT", "JLE", "JNC", "JMP"}),  # -1 < 1 signed, but unsigned >=
    ],
)
def test_conditional_jumps(a, b, taken):
    for j in ("JMP", "JZ", "JNZ", "JLT", "JGE", "JGT", "JLE", "JC", "JNC"):
        cpu, _ = machine(("LDI", 1, 0, a), ("LDI", 2, 0, b), ("CMP", 1, 2), (j, 0, 0, 0x300))
        run(cpu, 4)
        assert (cpu.pc == 0x300) == (j in taken), (j, a, b)


def test_logic_shifts_and_flags_cleared():
    cpu, _ = machine(
        ("LDI", 1, 0, 0xFFFF),
        ("ADDI", 1, 0, 1),  # sets C
        ("LDI", 1, 0, 0x8001),
        ("LDI", 2, 0, 1),
        ("SAR", 1, 2),
    )
    run(cpu, 5)
    assert cpu.regs[1] == 0xC000 and not F(cpu)["C"] and F(cpu)["N"]
    cpu, _ = machine(("LDI", 1, 0, 0x8001), ("LDI", 2, 0, 17), ("SHR", 1, 2))  # 17 & 15 = 1
    run(cpu, 3)
    assert cpu.regs[1] == 0x4000
    cpu, _ = machine(("LDI", 1, 0, 0x00F0), ("LDI", 2, 0, 0x0F0F), ("XOR", 1, 2), ("NOT", 2))
    run(cpu, 4)
    assert cpu.regs[1] == 0x0FFF and cpu.regs[2] == 0xF0F0


def test_mul_div_neg():
    cpu, _ = machine(("LDI", 1, 0, 300), ("LDI", 2, 0, 300), ("MUL", 1, 2))
    assert run(cpu, 3) == 1 + 1 + 3
    assert cpu.regs[1] == (90000 & 0xFFFF)
    cpu, _ = machine(("LDI", 1, 0, (-7) & 0xFFFF), ("LDI", 2, 0, 2), ("DIV", 1, 2))
    run(cpu, 3)
    assert cpu.regs[1] == (-3) & 0xFFFF  # truncates toward zero
    cpu, _ = machine(("LDI", 1, 0, 0x8000), ("LDI", 2, 0, 0xFFFF), ("DIV", 1, 2))
    run(cpu, 3)
    assert cpu.regs[1] == 0x8000  # -32768 / -1 wraps
    cpu, _ = machine(("LDI", 1, 0, 5), ("NEG", 1))
    run(cpu, 2)
    assert cpu.regs[1] == (-5) & 0xFFFF and F(cpu)["C"] and F(cpu)["N"]


def test_fmul_q88_and_saturation():
    q = lambda x: round(x * 256) & 0xFFFF  # noqa: E731
    cpu, _ = machine(("LDI", 1, 0, q(1.5)), ("LDI", 2, 0, q(-2.25)), ("FMUL", 1, 2))
    run(cpu, 3)
    assert cpu.regs[1] == q(-3.375)
    cpu, _ = machine(("LDI", 1, 0, q(100)), ("LDI", 2, 0, q(100)), ("FMUL", 1, 2))
    run(cpu, 3)
    assert cpu.regs[1] == 0x7FFF
    cpu, _ = machine(("LDI", 1, 0, q(100)), ("LDI", 2, 0, q(-100)), ("FMUL", 1, 2))
    run(cpu, 3)
    assert cpu.regs[1] == 0x8000


def test_load_store_and_absolute_addressing():
    cpu, bus = machine(
        ("LDI", 2, 0, 0x4000),
        ("LDI", 3, 0, 0xBEEF),
        ("ST", 2, 3, 4),  # mem[r2+4] = r3
        ("LD", 1, 2, 4),
        ("ST", isa.ZERO_BASE, 3, 0x5000),  # ST [0x5000], r3
        ("LD", 4, isa.ZERO_BASE, 0x5000),
        ("LD", 5, 2, (-0x4000 + 0x5000) & 0xFFFF),  # negative-ish offsets wrap
    )
    run(cpu, 7)
    assert bus.mem[0x4004] == 0xBEEF and cpu.regs[1] == 0xBEEF
    assert bus.mem[0x5000] == 0xBEEF and cpu.regs[4] == 0xBEEF and cpu.regs[5] == 0xBEEF


def test_push_pop_call_ret():
    sub = isa.CODE_BASE + 0x40
    cpu, bus = machine(
        ("LDI", 1, 0, 11),
        ("PUSH", 0, 1),
        ("CALL", 0, 0, sub),
        ("POP", 2),
        ("HALT",),
    )
    w0, w1 = E("LDI", 3, 0, 99)
    bus.mem[sub], bus.mem[sub + 1] = w0, w1
    bus.mem[sub + 2], bus.mem[sub + 3] = E("RET")
    run(cpu, 7)
    assert cpu.halted and cpu.regs[2] == 11 and cpu.regs[3] == 99 and cpu.regs[isa.SP] == 0x8000


def test_jr_and_callr():
    cpu, _ = machine(("LDI", 1, 0, 0x600), ("JR", 0, 1, 0x10))
    run(cpu, 2)
    assert cpu.pc == 0x610
    cpu, bus = machine(("LDI", 1, 0, 0x700), ("CALLR", 0, 1))
    run(cpu, 2)
    assert cpu.pc == 0x700 and bus.mem[0x7FFF] == isa.CODE_BASE + 4


def test_trap_and_iret_roundtrip():
    handler = 0x900
    cpu, bus = machine(
        ("EI",),
        ("LDI", 1, 0, 0),
        ("CMPI", 1, 0, 0),  # Z set
        ("TRAP", 0, 0, 42),
        ("HALT",),
        vectors={isa.VEC_TRAP: handler},
    )
    bus.mem[handler], bus.mem[handler + 1] = E("LDI", 2, 0, 7)
    bus.mem[handler + 2], bus.mem[handler + 3] = E("IRET")
    run(cpu, 4)
    assert cpu.pc == handler and bus.cause == isa.CAUSE_TRAP and bus.traparg == 42
    assert not cpu.flags & isa.FLAG_I
    assert bus.mem[0x7FFF] == isa.CODE_BASE + 8  # pushed pc = next instruction
    run(cpu, 2)
    assert cpu.pc == isa.CODE_BASE + 8 and cpu.flags & isa.FLAG_I and cpu.flags & isa.FLAG_Z
    assert cpu.regs[isa.SP] == 0x8000
    run(cpu, 1)
    assert cpu.halted and cpu.regs[2] == 7


def test_irq_only_when_enabled_lowest_vector_wins():
    cpu, bus = machine(
        ("NOP",), ("EI",), ("NOP",), vectors={isa.VEC_TIMER: 0xA00, isa.VEC_UART: 0xB00}
    )
    bus.irqs = {isa.VEC_UART, isa.VEC_TIMER}
    run(cpu, 2)  # NOP, EI: masked
    assert cpu.pc == isa.CODE_BASE + 4
    assert cpu.step() == isa.IRQ_ENTRY_CYCLES
    assert cpu.pc == 0xA00 and bus.cause == isa.CAUSE_TIMER and bus.irqs == {isa.VEC_UART}
    assert bus.mem[0x7FFF] == isa.CODE_BASE + 4  # the NOP that hadn't run yet
    assert bus.mem[0x7FFE] & isa.FLAG_I  # saved flags had I set
    assert cpu.step() != isa.IRQ_ENTRY_CYCLES  # I cleared on entry: no nesting


@pytest.mark.parametrize(
    "prog,cause",
    [
        ([("LDI", 1, 0, 1), ("LDI", 2, 0, 0), ("DIV", 1, 2)], isa.CAUSE_DIV0),
        ([("NOP",), ("NOP",), ("ST", isa.ZERO_BASE, 1, isa.MMIO_BASE)], isa.CAUSE_BUS),
        ([("NOP",), ("NOP",), ("MOV", 1, 9)], isa.CAUSE_ILLEGAL),  # register field > 7
        ([("NOP",), ("NOP",), ("LD", isa.ZERO_BASE, 1, 0)], isa.CAUSE_ILLEGAL),  # ZERO_BASE as rd
    ],
)
def test_faults_are_precise(prog, cause):
    cpu, bus = machine(*prog, vectors={isa.VEC_FAULT: 0xC00})
    before = list(cpu.regs)
    run(cpu, 2)
    before = list(cpu.regs)
    bad_pc = cpu.pc
    cpu.step()
    assert cpu.pc == 0xC00 and bus.cause == cause and bus.faultpc == bad_pc
    assert bus.mem[0x7FFF] == bad_pc  # pushed pc = faulting instruction
    assert cpu.regs[:7] == before[:7] and cpu.regs[isa.SP] == 0x8000 - 2


def test_illegal_opcode_fault():
    cpu, bus = machine(vectors={isa.VEC_FAULT: 0xC00})
    bus.mem[isa.CODE_BASE] = 0xFF00
    cpu.step()
    assert cpu.pc == 0xC00 and bus.cause == isa.CAUSE_ILLEGAL


def test_faults_taken_with_interrupts_disabled_and_double_fault():
    cpu, bus = machine(("DIV", 1, 2), vectors={isa.VEC_FAULT: 0xC00})
    assert not cpu.flags & isa.FLAG_I
    cpu.step()
    assert cpu.pc == 0xC00 and not cpu.halted
    # stack points into MMIO: pushing the fault frame itself faults -> double fault
    cpu, bus = machine(("DIV", 1, 2), sp=isa.MMIO_BASE + 2, vectors={isa.VEC_FAULT: 0xC00})
    cpu.step()
    assert cpu.halted and cpu.double_fault


def test_trap_with_bad_stack_faults():
    cpu, bus = machine(("TRAP", 0, 0, 1), sp=0, vectors={isa.VEC_FAULT: 0xC00})
    bus.readonly = {0xFFFF, 0xFFFE}  # sp-1, sp-2 wrap into read-only
    cpu.step()
    assert cpu.halted and cpu.double_fault  # fault frame also lands there


def test_halt_requested_by_bus():
    cpu, bus = machine(("NOP",), ("NOP",))
    bus.halt_requested = True
    cpu.step()
    assert cpu.halted and cpu.pc == isa.CODE_BASE


def test_cycle_costs():
    cpu, bus = machine(
        ("LD", 1, isa.ZERO_BASE, 0x100), ("DIV", 1, 2), vectors={isa.VEC_FAULT: 0xC00}
    )
    assert cpu.step() == isa.CYCLES["LD"]
    assert cpu.step() == 1 + isa.IRQ_ENTRY_CYCLES  # div0 fault entry


def test_encode_roundtrip_every_opcode_executes():
    """Every opcode decodes and runs without AssertionError from a sane state."""
    for name in isa.OPCODES:
        if name in ("DIV",):
            continue
        cpu, bus = machine((name, 1, 2, 0x4000), vectors={v: 0xC00 for v in range(16)})
        cpu.regs[2] = 3
        cpu.step()
        assert not cpu.double_fault, name
