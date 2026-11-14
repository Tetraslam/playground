"""T16 CPU core: fetch/decode/execute, flags, interrupts, faults (owner: agent 2).

The CPU talks to the bus through `read`, `write`, `pending_irq` (or the cached
`bus.irq` attribute), `pending_nmi`, `ack_irq` and the exception registers
(`cause`, `traparg`, `faultpc`, `halt_requested`). `step()` executes one
instruction and returns its cycles without advancing time; `run(cycles)` is the
fast path: it loops step + `bus.tick` itself and returns the cycles spent.

Speed: each instruction is compiled once into a closure that returns the next
pc, cached per address together with the two words it was decoded from. The
cache entry is reused only while `mem[pc]` and `mem[pc+1]` still hold those
words, so self-modifying code and injected bit flips are seen on the very next
fetch. RAM (< MMIO_BASE) is indexed directly; MMIO goes through the bus.

Instructions commit atomically: every bus access happens before any register,
sp, pc or flag changes, so a faulting instruction leaves the machine exactly as
it was and the handler sees the faulting pc.
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
MMIO = isa.MMIO_BASE
FZ, FN, FC, FV, FI = isa.FLAG_Z, isa.FLAG_N, isa.FLAG_C, isa.FLAG_V, isa.FLAG_I
ARITH_FLAGS = FZ | FN | FC | FV
SP = isa.SP
ZB = isa.ZERO_BASE

# which register fields each operand form uses: (rd used, rs used)
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


def sext(x: int) -> int:
    x &= M16
    return x - 0x10000 if x & SIGN else x


def _zn(r: int) -> int:
    return (FZ if r == 0 else 0) | (FN if r & SIGN else 0)


# Z/N flags for every 16-bit result, so hot paths do one list index
ZN = [_zn(r) for r in range(0x10000)]


class Fault(Exception):
    """Raised inside execute; turned into a FAULT exception entry."""

    def __init__(self, cause: int):
        super().__init__(cause)
        self.cause = cause


class _Halt(Exception):
    pass


class CPU:
    def __init__(self, bus):
        self.bus = bus
        self.regs = [0] * 8
        self.pc = 0
        self.flags = 0
        self.halted = False
        self.double_fault = False
        self.instret = 0  # instructions retired
        self.last: tuple[int, str] | None = None  # (pc, mnemonic | "IRQn" | "NMI" | "FAULT")
        self._cache: list = [None] * 0x10000
        self._bound = (None, None)  # (regs, mem) the cached closures were compiled against
        self.reset()  # pc = mem[VEC_RESET]; call reset() again after loading an image

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

    def flush(self) -> None:
        """Drop all decoded instructions (never required for correctness)."""
        self._cache = [None] * 0x10000

    # ---- execution ---------------------------------------------------

    def step(self) -> int:
        """Take a pending NMI/IRQ or execute one instruction. Returns cycles (1 when halted)."""
        bus = self.bus
        if bus.halt_requested:
            self.halted = True
        if self.halted:
            return 1
        c = self._interrupt(bus)
        if c:
            return c
        pc = self.pc
        e = self._fetch(pc)
        try:
            self.pc = e[2]()
        except Fault as f:
            return self._fault_entry(f.cause, pc)
        except BusError:
            return self._fault_entry(isa.CAUSE_BUS, pc)
        self.instret += 1
        self.last = (pc, e[4])
        return e[3]

    def run(self, cycles: int) -> int:
        """Execute until at least `cycles` cycles have elapsed or the CPU halts,
        calling bus.tick after every instruction/entry. Returns cycles spent."""
        bus = self.bus
        tick = bus.tick
        nmi = getattr(bus, "pending_nmi", None)
        irq_attr = hasattr(bus, "irq")
        pending = bus.pending_irq
        cache = self._cache
        if self._bound[0] is not self.regs or self._bound[1] is not bus.mem:
            self._rebind()
            cache = self._cache
        mem = bus.mem
        regs = self.regs
        spent = 0
        n = 0
        e = None
        pc = self.pc
        try:
            while spent < cycles:
                if bus.halt_requested:
                    self.halted = True
                if self.halted:
                    break
                # interrupts: NMI always, IRQ only with I set
                if (nmi is not None and nmi()) or (
                    self.flags & FI and (bus.irq if irq_attr else pending()) is not None
                ):
                    c = self._interrupt(bus)
                    if c:
                        tick(c)
                        spent += c
                        continue
                if self.regs is not regs:  # someone swapped the register file
                    self._rebind()
                    cache, regs = self._cache, self.regs
                pc = self.pc
                e = cache[pc]
                if e is None or mem[pc] != e[0] or mem[(pc + 1) & M16] != e[1]:
                    e = self._fetch(pc)
                try:
                    self.pc = e[2]()
                except Fault as f:
                    c = self._fault_entry(f.cause, pc)
                    tick(c)
                    spent += c
                    continue
                except BusError:
                    c = self._fault_entry(isa.CAUSE_BUS, pc)
                    tick(c)
                    spent += c
                    continue
                n += 1
                c = e[3]
                tick(c)
                spent += c
        finally:
            self.instret += n
            if e is not None and n:
                self.last = (pc, e[4])
        return spent

    # ---- interrupts / exceptions --------------------------------------

    def _interrupt(self, bus) -> int:
        nmi = getattr(bus, "pending_nmi", None)
        if nmi is not None and nmi():
            bus.ack_irq(isa.VEC_WDOG)
            self.last = (self.pc, "NMI")
            self._enter(isa.VEC_WDOG, isa.CAUSE_WDOG, self.pc)
            return isa.IRQ_ENTRY_CYCLES
        if self.flags & FI:
            vec = bus.pending_irq()
            if vec is not None:
                bus.ack_irq(vec)
                self.last = (self.pc, f"IRQ{vec}")
                self._enter(vec, vec, self.pc)
                return isa.IRQ_ENTRY_CYCLES
        return 0

    def _enter(self, vector: int, cause: int, push_pc: int, *, is_fault: bool = False) -> None:
        """Exception entry. BusError during IRQ/TRAP entry becomes a fault; during
        fault entry it is a double fault (halt)."""
        sp = self.regs[SP]
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
        self.regs[SP] = (sp - 2) & M16
        self.flags &= ~FI
        self.bus.cause = cause
        self.pc = target & M16

    def _fault(self, cause: int, pc: int) -> None:
        self.bus.faultpc = pc & M16
        self._enter(isa.VEC_FAULT, cause, pc, is_fault=True)

    def _fault_entry(self, cause: int, pc: int) -> int:
        self.last = (pc, "FAULT")
        self.pc = pc
        self._fault(cause, pc)
        return 1 + isa.IRQ_ENTRY_CYCLES

    # ---- decode / compile -----------------------------------------------

    def _rebind(self) -> None:
        self._cache = [None] * 0x10000
        self._bound = (self.regs, self.bus.mem)

    def _fetch(self, pc: int) -> tuple:
        """Decode the instruction at pc -> (w0, w1, fn, cycles, name), caching RAM code."""
        if self._bound[0] is not self.regs or self._bound[1] is not self.bus.mem:
            self._rebind()
        if pc < MMIO - 1:
            mem = self.bus.mem
            w0, w1 = mem[pc], mem[pc + 1]
            e = self._cache[pc]
            if e is not None and e[0] == w0 and e[1] == w1:
                return e
            e = self._compile(pc, w0, w1)
            self._cache[pc] = e
            return e
        # fetching from MMIO (or wrapping past it): never cached, may raise BusError
        try:
            w0 = self.bus.read(pc) & M16
            w1 = self.bus.read((pc + 1) & M16) & M16
        except BusError:
            return (None, None, _raiser(Fault(isa.CAUSE_BUS)), 1, "FAULT")
        return self._compile(pc, w0, w1)

    def _compile(self, pc: int, w0: int, w1: int) -> tuple:
        name, rd, rs, imm = isa.decode(w0, w1)
        if name is None:
            return (w0, w1, _raiser(Fault(isa.CAUSE_ILLEGAL)), 1, "ILLEGAL")
        form = _FORM[name]
        use_rd, use_rs = _FIELDS[form]
        rd_ok = rd <= 7 or (form == "mem_st" and rd == ZB)
        rs_ok = rs <= 7 or (form == "mem_ld" and rs == ZB)
        if (use_rd and not rd_ok) or (use_rs and not rs_ok):
            return (w0, w1, _raiser(Fault(isa.CAUSE_ILLEGAL)), 1, "ILLEGAL")
        fn = _build(self, name, rd, rs, imm, (pc + 2) & M16)
        cycles = isa.CYCLES[name] + (isa.IRQ_ENTRY_CYCLES if name == "TRAP" else 0)
        return (w0, w1, fn, cycles, name)


def _raiser(exc: Exception):
    def f():
        raise exc

    return f


def _build(cpu: CPU, name: str, rd: int, rs: int, imm: int, nxt: int):
    """Compile one decoded instruction into a zero-arg closure returning the new pc."""
    regs = cpu.regs
    bus = cpu.bus
    mem = bus.mem
    read, write = bus.read, bus.write

    if name == "NOP":
        return lambda: nxt
    if name == "HALT":

        def f():
            cpu.halted = True
            return nxt

        return f
    if name == "MOV":

        def f():
            regs[rd] = regs[rs]
            return nxt

        return f
    if name == "LDI":

        def f():
            regs[rd] = imm
            return nxt

        return f

    if name == "LD":
        if rs == ZB:
            a = imm & M16
            if a < MMIO:

                def f():
                    regs[rd] = mem[a]
                    return nxt
            else:

                def f():
                    regs[rd] = read(a) & M16
                    return nxt

            return f

        def f():
            a = (regs[rs] + imm) & M16
            regs[rd] = mem[a] if a < MMIO else read(a) & M16
            return nxt

        return f
    if name == "ST":
        if rd == ZB:
            a = imm & M16
            if a < MMIO:

                def f():
                    mem[a] = regs[rs]
                    return nxt
            else:

                def f():
                    write(a, regs[rs])
                    return nxt

            return f

        def f():
            a = (regs[rd] + imm) & M16
            if a < MMIO:
                mem[a] = regs[rs]
            else:
                write(a, regs[rs])
            return nxt

        return f

    # ---- arithmetic with C/V ------------------------------------------
    if name in ("ADD", "ADDI"):
        use_imm = name == "ADDI"

        def f():
            a = regs[rd]
            b = imm if use_imm else regs[rs]
            full = a + b
            r = full & M16
            fl = (cpu.flags & FI) | ZN[r]
            if full > M16:
                fl |= FC
            if (a ^ r) & (b ^ r) & SIGN:
                fl |= FV
            regs[rd] = r
            cpu.flags = fl
            return nxt

        return f
    if name in ("SUB", "CMP", "CMPI", "NEG"):
        store = name in ("SUB", "NEG")
        kind = name

        def f():
            if kind == "NEG":
                a, b = 0, regs[rd]
            else:
                a = regs[rd]
                b = imm if kind == "CMPI" else regs[rs]
            r = (a - b) & M16
            fl = (cpu.flags & FI) | ZN[r]
            if a < b:
                fl |= FC
            if (a ^ b) & (a ^ r) & SIGN:
                fl |= FV
            if store:
                regs[rd] = r
            cpu.flags = fl
            return nxt

        return f

    # ---- logic: Z/N from result, C/V cleared --------------------------
    logic = {
        "AND": lambda a, b: a & b,
        "OR": lambda a, b: a | b,
        "XOR": lambda a, b: a ^ b,
        "SHL": lambda a, b: (a << (b & 15)) & M16,
        "SHR": lambda a, b: a >> (b & 15),
        "SAR": lambda a, b: (sext(a) >> (b & 15)) & M16,
        "MUL": lambda a, b: (a * b) & M16,
        "NOT": lambda a, b: ~a & M16,
        "FMUL": lambda a, b: max(-0x8000, min(0x7FFF, (sext(a) * sext(b)) >> 8)) & M16,
    }
    if name in logic:
        op = logic[name]
        src = rs if _FORM[name] == "rd,rs" else rd

        def f():
            r = op(regs[rd], regs[src])
            regs[rd] = r
            cpu.flags = (cpu.flags & FI) | ZN[r]
            return nxt

        return f
    if name == "DIV":

        def f():
            sa, sb = sext(regs[rd]), sext(regs[rs])
            if sb == 0:
                raise Fault(isa.CAUSE_DIV0)
            q = abs(sa) // abs(sb)
            if (sa < 0) != (sb < 0):
                q = -q
            r = q & M16
            regs[rd] = r
            cpu.flags = (cpu.flags & FI) | ZN[r]
            return nxt

        return f

    # ---- control flow ---------------------------------------------------
    t = imm & M16
    if name == "JMP":
        return lambda: t
    cond = {
        "JZ": lambda f: f & FZ,
        "JNZ": lambda f: not f & FZ,
        "JLT": lambda f: bool(f & FN) != bool(f & FV),
        "JGE": lambda f: bool(f & FN) == bool(f & FV),
        "JGT": lambda f: not f & FZ and bool(f & FN) == bool(f & FV),
        "JLE": lambda f: f & FZ or bool(f & FN) != bool(f & FV),
        "JC": lambda f: f & FC,
        "JNC": lambda f: not f & FC,
    }
    if name in cond:
        # precompute the 32 possible flag states once per instruction
        table = [t if cond[name](fl) else nxt for fl in range(32)]
        return lambda: table[cpu.flags & 31]
    if name == "JR":
        return lambda: (regs[rs] + imm) & M16

    if name in ("CALL", "CALLR"):
        absolute = name == "CALL"

        def f():
            sp = (regs[SP] - 1) & M16
            target = t if absolute else regs[rs]
            if sp < MMIO:
                mem[sp] = nxt
            else:
                write(sp, nxt)
            regs[SP] = sp
            return target

        return f
    if name == "RET":

        def f():
            sp = regs[SP]
            target = mem[sp] if sp < MMIO else read(sp) & M16
            regs[SP] = (sp + 1) & M16
            return target

        return f
    if name == "PUSH":

        def f():
            sp = (regs[SP] - 1) & M16
            if sp < MMIO:
                mem[sp] = regs[rs]
            else:
                write(sp, regs[rs])
            regs[SP] = sp
            return nxt

        return f
    if name == "POP":

        def f():
            sp = regs[SP]
            v = mem[sp] if sp < MMIO else read(sp) & M16
            regs[SP] = (sp + 1) & M16
            regs[rd] = v  # POP sp gets the popped value
            return nxt

        return f
    if name == "IRET":

        def f():
            sp = regs[SP]
            fl = read(sp) & M16
            target = read((sp + 1) & M16) & M16
            regs[SP] = (sp + 2) & M16
            cpu.flags = fl & (ARITH_FLAGS | FI)
            return target

        return f
    if name == "TRAP":

        def f():
            bus.traparg = imm
            cpu.pc = nxt
            cpu._enter(isa.VEC_TRAP, isa.CAUSE_TRAP, nxt)
            return cpu.pc

        return f
    if name == "EI":

        def f():
            cpu.flags |= FI
            return nxt

        return f
    if name == "DI":

        def f():
            cpu.flags &= ~FI
            return nxt

        return f
    raise AssertionError(f"unimplemented opcode {name}")  # pragma: no cover
