"""T16 CPU core: fetch/decode/execute, flags, interrupts, faults (owner: agent 2).

The CPU only talks to the bus through `read`, `write`, `pending_irq`, `ack_irq`
and the exception registers (`cause`, `traparg`, `faultpc`, `halt_requested`).
It never advances time: `step()` returns the cycles it spent and the machine
calls `bus.tick(cycles)`.

Instructions commit atomically: every bus access happens before any register,
sp, pc or flag is changed, so a faulting instruction leaves the machine exactly
as it was and the handler sees the faulting pc.
"""

from __future__ import annotations

from . import isa

try:  # bus.py may land after cpu.py; any exception class named BusError works
    from .bus import BusError
except ImportError:  # pragma: no cover

    class BusError(Exception):
        pass


M16 = 0xFFFF
SIGN = 0x8000
ARITH_FLAGS = isa.FLAG_Z | isa.FLAG_N | isa.FLAG_C | isa.FLAG_V

# which register fields each operand form actually uses: (rd used, rs used)
_FIELDS = {
    "": (False, False),
    "rd,rs": (True, True),
    "rd,imm": (True, False),
    "rd": (True, False),
    "rs": (False, True),
    "imm": (False, False),
    "mem_ld": (True, True),
    "mem_st": (True, True),
    "rs,imm": (False, True),
}
_FORM = {name: form for name, (_, form) in isa.OPCODES.items()}

_JUMP_COND = {
    "JMP": lambda z, n, c, v: True,
    "JZ": lambda z, n, c, v: z,
    "JNZ": lambda z, n, c, v: not z,
    "JLT": lambda z, n, c, v: n != v,
    "JGE": lambda z, n, c, v: n == v,
    "JGT": lambda z, n, c, v: not z and n == v,
    "JLE": lambda z, n, c, v: z or n != v,
    "JC": lambda z, n, c, v: c,
    "JNC": lambda z, n, c, v: not c,
}


def sext(x: int) -> int:
    x &= M16
    return x - 0x10000 if x & SIGN else x


class Fault(Exception):
    """Raised inside execute; turned into a FAULT exception entry by step()."""

    def __init__(self, cause: int):
        super().__init__(cause)
        self.cause = cause


class CPU:
    def __init__(self, bus):
        self.bus = bus
        self.regs = [0] * 8
        self.pc = 0
        self.flags = 0
        self.halted = False
        self.double_fault = False
        self.instret = 0  # instructions retired
        self.last: tuple[int, str] | None = None  # (pc, mnemonic) of last instruction / entry

    # ---- lifecycle ---------------------------------------------------

    def reset(self) -> None:
        self.regs = [0] * 8
        self.flags = 0
        self.pc = self.bus.mem[isa.VEC_RESET] & M16
        self.halted = False
        self.double_fault = False
        self.last = None

    def state(self) -> dict:
        return {
            "pc": self.pc,
            "regs": list(self.regs),
            "flags": self.flags,
            "halted": self.halted,
            "double_fault": self.double_fault,
            "instret": self.instret,
        }

    # ---- stepping ----------------------------------------------------

    def step(self) -> int:
        """Take a pending IRQ (if I set) or execute one instruction. Returns cycles."""
        if getattr(self.bus, "halt_requested", False):
            self.halted = True
        if self.halted:
            return 1
        if self.flags & isa.FLAG_I:
            vec = self.bus.pending_irq()
            if vec is not None:
                self.bus.ack_irq(vec)
                self.last = (self.pc, f"IRQ{vec}")
                self._enter(vec, vec, self.pc)
                return isa.IRQ_ENTRY_CYCLES
        pc = self.pc
        try:
            name, cycles = self._execute(pc)
        except Fault as f:
            self.last = (pc, "FAULT")
            self._fault(f.cause, pc)
            return 1 + isa.IRQ_ENTRY_CYCLES
        except BusError:
            self.last = (pc, "FAULT")
            self._fault(isa.CAUSE_BUS, pc)
            return 1 + isa.IRQ_ENTRY_CYCLES
        self.instret += 1
        self.last = (pc, name)
        return cycles

    # ---- exceptions --------------------------------------------------

    def _enter(self, vector: int, cause: int, push_pc: int, *, is_fault: bool = False) -> None:
        """Exception entry. BusError during IRQ/TRAP entry becomes a fault; during
        fault entry it is a double fault (halt)."""
        sp = self.regs[isa.SP]
        try:
            self.bus.write((sp - 1) & M16, push_pc & M16)
            self.bus.write((sp - 2) & M16, self.flags)
            target = self.bus.read(vector)
        except BusError:
            if is_fault:
                self.double_fault = self.halted = True
                return
            self._fault(isa.CAUSE_BUS, push_pc)
            return
        self.regs[isa.SP] = (sp - 2) & M16
        self.flags &= ~isa.FLAG_I
        self.bus.cause = cause
        self.pc = target & M16

    def _fault(self, cause: int, pc: int) -> None:
        self.bus.faultpc = pc & M16
        self._enter(isa.VEC_FAULT, cause, pc, is_fault=True)

    # ---- flags helpers ------------------------------------------------

    def _zn(self, r: int) -> int:
        f = self.flags & ~ARITH_FLAGS
        if r == 0:
            f |= isa.FLAG_Z
        if r & SIGN:
            f |= isa.FLAG_N
        return f

    def _add(self, a: int, b: int) -> tuple[int, int]:
        full = a + b
        r = full & M16
        f = self._zn(r)
        if full > M16:
            f |= isa.FLAG_C
        if (a ^ r) & (b ^ r) & SIGN:
            f |= isa.FLAG_V
        return r, f

    def _sub(self, a: int, b: int) -> tuple[int, int]:
        r = (a - b) & M16
        f = self._zn(r)
        if a < b:
            f |= isa.FLAG_C
        if (a ^ b) & (a ^ r) & SIGN:
            f |= isa.FLAG_V
        return r, f

    # ---- execute -----------------------------------------------------

    def _execute(self, pc: int) -> tuple[str, int]:
        bus = self.bus
        w0 = bus.read(pc)
        w1 = bus.read((pc + 1) & M16)
        name, rd, rs, imm = isa.decode(w0 & M16, w1 & M16)
        if name is None:
            raise Fault(isa.CAUSE_ILLEGAL)
        form = _FORM[name]
        use_rd, use_rs = _FIELDS[form]
        # base register may be ZERO_BASE for memory forms; everything else must be r0..r7
        rd_ok = rd <= 7 or (form == "mem_st" and rd == isa.ZERO_BASE)
        rs_ok = rs <= 7 or (form == "mem_ld" and rs == isa.ZERO_BASE)
        if (use_rd and not rd_ok) or (use_rs and not rs_ok):
            raise Fault(isa.CAUSE_ILLEGAL)

        regs = self.regs
        nxt = (pc + 2) & M16
        cycles = isa.CYCLES[name]
        a = regs[rd] if rd <= 7 else 0
        b = regs[rs] if rs <= 7 else 0

        def done(new_pc: int = nxt) -> tuple[str, int]:
            self.pc = new_pc & M16
            return name, cycles

        if name == "NOP":
            return done()
        if name == "HALT":
            self.halted = True
            return done()
        if name == "MOV":
            regs[rd] = b
            return done()
        if name == "LDI":
            regs[rd] = imm
            return done()
        if name == "LD":
            regs[rd] = bus.read((b + imm) & M16) & M16
            return done()
        if name == "ST":
            bus.write((a + imm) & M16, b)
            return done()

        if name in ("ADD", "ADDI"):
            r, self_flags = self._add(a, b if name == "ADD" else imm)
            regs[rd] = r
            self.flags = self_flags
            return done()
        if name in ("SUB", "CMP", "CMPI"):
            r, f = self._sub(a, imm if name == "CMPI" else b)
            if name == "SUB":
                regs[rd] = r
            self.flags = f
            return done()
        if name == "NEG":
            r, f = self._sub(0, a)
            regs[rd] = r
            self.flags = f
            return done()

        logic = {
            "AND": lambda: a & b,
            "OR": lambda: a | b,
            "XOR": lambda: a ^ b,
            "SHL": lambda: (a << (b & 15)) & M16,
            "SHR": lambda: a >> (b & 15),
            "SAR": lambda: (sext(a) >> (b & 15)) & M16,
            "MUL": lambda: (a * b) & M16,
            "NOT": lambda: ~a & M16,
        }
        if name in logic:
            r = logic[name]()
            regs[rd] = r
            self.flags = self._zn(r)
            return done()
        if name == "DIV":
            sa, sb = sext(a), sext(b)
            if sb == 0:
                raise Fault(isa.CAUSE_DIV0)
            q = abs(sa) // abs(sb)
            if (sa < 0) != (sb < 0):
                q = -q
            r = q & M16
            regs[rd] = r
            self.flags = self._zn(r)
            return done()
        if name == "FMUL":
            p = (sext(a) * sext(b)) >> 8
            p = max(-0x8000, min(0x7FFF, p))
            r = p & M16
            regs[rd] = r
            self.flags = self._zn(r)
            return done()

        if name in _JUMP_COND:
            f = self.flags
            taken = _JUMP_COND[name](
                bool(f & isa.FLAG_Z),
                bool(f & isa.FLAG_N),
                bool(f & isa.FLAG_C),
                bool(f & isa.FLAG_V),
            )
            return done(imm if taken else nxt)
        if name == "JR":
            return done(b + imm)

        sp = regs[isa.SP]
        if name in ("CALL", "CALLR"):
            bus.write((sp - 1) & M16, nxt)
            regs[isa.SP] = (sp - 1) & M16
            return done(imm if name == "CALL" else b)
        if name == "RET":
            target = bus.read(sp)
            regs[isa.SP] = (sp + 1) & M16
            return done(target)
        if name == "PUSH":
            bus.write((sp - 1) & M16, b)
            regs[isa.SP] = (sp - 1) & M16
            return done()
        if name == "POP":
            v = bus.read(sp) & M16
            regs[isa.SP] = (sp + 1) & M16
            regs[rd] = v  # POP sp gets the popped value, matching x = mem[sp]; sp += 1; rd = x
            return done()
        if name == "IRET":
            flags = bus.read(sp) & M16
            target = bus.read((sp + 1) & M16)
            regs[isa.SP] = (sp + 2) & M16
            self.flags = flags & (ARITH_FLAGS | isa.FLAG_I)
            return done(target)
        if name == "TRAP":
            bus.traparg = imm
            self.pc = nxt
            self._enter(isa.VEC_TRAP, isa.CAUSE_TRAP, nxt)
            return name, cycles + isa.IRQ_ENTRY_CYCLES
        if name == "EI":
            self.flags |= isa.FLAG_I
            return done()
        if name == "DI":
            self.flags &= ~isa.FLAG_I
            return done()
        raise AssertionError(f"unimplemented opcode {name}")  # pragma: no cover
