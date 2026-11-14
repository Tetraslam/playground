"""T16 instruction set + memory map. THE shared contract (owner: agent 1).

Every instruction is exactly 2 words:
    word0 = (opcode << 8) | (rd << 4) | rs
    word1 = imm16 (always present; 0 when unused)

Registers r0..r7 (16-bit). r7 is the stack pointer by convention (alias `sp`).
Stack grows down; PUSH does `sp -= 1; mem[sp] = x`, POP does `x = mem[sp]; sp += 1`.
PC is not a general register. FLAGS bits: Z N C V I (see FLAG_*).
Memory: 65536 words, word-addressed. All arithmetic wraps at 16 bits.

Change this file only via agent 1 (tell them first).
"""

# ---- flags -------------------------------------------------------------
FLAG_Z = 1 << 0  # result == 0
FLAG_N = 1 << 1  # result bit15 set
FLAG_C = 1 << 2  # unsigned carry out (ADD) / borrow (SUB, CMP: set when rd < rs unsigned)
FLAG_V = 1 << 3  # signed overflow
FLAG_I = 1 << 4  # interrupts enabled

# ---- opcodes -----------------------------------------------------------
# name: (opcode, operand form)
# forms: ""         no operands
#        "rd,rs"    two registers
#        "rd,imm"   register + immediate
#        "rd"       one register (in rd field)
#        "rs"       one register (in rs field)
#        "imm"      immediate only
#        "mem_ld"   LD rd, [rs+imm]   asm accepts [rs], [rs+imm], [rs-imm], [imm]
#        "mem_st"   ST [rd+imm], rs   asm accepts [rd], [rd+imm], [rd-imm], [imm]
#        "rs,imm"   JR rs, imm  -> pc = rs + imm
# Absolute form [imm] encodes the base register field as ZERO_BASE (15), which
# reads as 0 for LD/ST addressing only. Any other register field > 7 is an
# illegal instruction (FAULT, CAUSE_ILLEGAL).
#
# Flags: ALU ops (ADD SUB AND OR XOR SHL SHR SAR MUL DIV FMUL ADDI CMP CMPI NEG NOT)
# set Z and N from the result. ADD/ADDI/SUB/CMP/CMPI/NEG also set C and V.
# Logic/shift/mul/div/fmul clear C and V. MOV/LDI/LD/ST/PUSH/POP/jumps leave flags.
ZERO_BASE = 15

OPCODES = {
    "NOP": (0x00, ""),
    "HALT": (0x01, ""),          # stop the CPU (cpu.halted = True)
    "MOV": (0x02, "rd,rs"),      # rd = rs
    "LDI": (0x03, "rd,imm"),     # rd = imm
    "LD": (0x04, "mem_ld"),      # rd = mem[rs + imm]
    "ST": (0x05, "mem_st"),      # mem[rd + imm] = rs
    "ADD": (0x06, "rd,rs"),
    "SUB": (0x07, "rd,rs"),      # rd = rd - rs
    "AND": (0x08, "rd,rs"),
    "OR": (0x09, "rd,rs"),
    "XOR": (0x0A, "rd,rs"),
    "SHL": (0x0B, "rd,rs"),      # rd <<= (rs & 15)
    "SHR": (0x0C, "rd,rs"),      # logical
    "SAR": (0x0D, "rd,rs"),      # arithmetic
    "MUL": (0x0E, "rd,rs"),      # low 16 bits of product
    "DIV": (0x0F, "rd,rs"),      # signed, truncating toward 0; rs==0 -> FAULT (CAUSE_DIV0)
    "ADDI": (0x10, "rd,imm"),    # rd += imm (negative imm stored two's complement)
    "CMP": (0x11, "rd,rs"),      # flags of rd - rs, rd unchanged
    "CMPI": (0x12, "rd,imm"),
    "JMP": (0x13, "imm"),
    "JZ": (0x14, "imm"),         # Z
    "JNZ": (0x15, "imm"),        # !Z
    "JLT": (0x16, "imm"),        # signed <   : N != V
    "JGE": (0x17, "imm"),        # signed >=  : N == V
    "JGT": (0x18, "imm"),        # signed >   : !Z and N == V
    "JLE": (0x19, "imm"),        # signed <=  : Z or N != V
    "JC": (0x1A, "imm"),         # C (unsigned < after CMP)
    "JNC": (0x1B, "imm"),        # !C (unsigned >= after CMP)
    "JR": (0x1C, "rs,imm"),      # pc = rs + imm
    "CALL": (0x1D, "imm"),       # push(pc_next); pc = imm
    "CALLR": (0x1E, "rs"),       # push(pc_next); pc = rs
    "RET": (0x1F, ""),           # pc = pop()
    "PUSH": (0x20, "rs"),
    "POP": (0x21, "rd"),
    "TRAP": (0x22, "imm"),       # software interrupt: vector VEC_TRAP, CAUSE_TRAP, TRAPARG = imm
    "IRET": (0x23, ""),          # flags = pop(); pc = pop()
    "EI": (0x24, ""),            # set I
    "DI": (0x25, ""),            # clear I
    "FMUL": (0x26, "rd,rs"),     # Q8.8 signed: rd = (sext(rd) * sext(rs)) >> 8 (arith), saturating to int16
    "NEG": (0x27, "rd"),         # rd = -rd
    "NOT": (0x28, "rd"),         # rd = ~rd
}
OPNAMES = {code: name for name, (code, _) in OPCODES.items()}
REGS = {f"r{i}": i for i in range(8)} | {"sp": 7}
SP = 7

# Cycle cost: 1 per instruction except below; interrupt entry = IRQ_ENTRY_CYCLES.
CYCLES = {name: 1 for name in OPCODES} | {
    "LD": 2, "ST": 2, "PUSH": 2, "POP": 2, "CALL": 2, "CALLR": 2, "RET": 2,
    "MUL": 3, "FMUL": 3, "DIV": 8, "IRET": 3,
}
IRQ_ENTRY_CYCLES = 4

# ---- interrupts / exceptions ------------------------------------------
# Entry sequence (IRQ, TRAP, or FAULT): push(pc), push(flags), clear I,
# set bus.cause (and bus.traparg / bus.faultpc), pc = mem[vector].
# Faults and TRAP are taken even when I is clear. Pushed pc = address of the
# NEXT instruction for TRAP/IRQ, of the FAULTING instruction for faults.
# A fault raised while entering the fault handler (e.g. stack push bus error)
# -> cpu.double_fault = cpu.halted = True.
# IRQs are only taken between instructions when I is set; lowest vector wins.
# EXCEPTION: the watchdog is non-maskable. CPU checks bus.pending_nmi() before
# anything else each step and takes VEC_WDOG regardless of I (then bus.ack_irq(VEC_WDOG)).
VEC_RESET = 0x0000     # mem[0] = reset entry point
VEC_TRAP = 0x0001
VEC_TIMER = 0x0002
VEC_UART = 0x0003      # rx byte available
VEC_GPIO = 0x0004      # button press edge
VEC_FAULT = 0x0005     # illegal opcode/register, div0, bus error
VEC_WDOG = 0x0006      # watchdog expired
NUM_VECTORS = 16       # mem[0..15] reserved for vectors

CAUSE_TRAP = 1
CAUSE_TIMER = 2
CAUSE_UART = 3
CAUSE_GPIO = 4
CAUSE_WDOG = 6
CAUSE_ILLEGAL = 0x10
CAUSE_DIV0 = 0x11
CAUSE_BUS = 0x12       # write to read-only MMIO / unmapped MMIO

# ---- memory map --------------------------------------------------------
CODE_BASE = 0x0010     # assembler default origin, right after the vector table
RAM_TOP = 0xEFFF       # stacks live below this by convention
MMIO_BASE = 0xFF00     # 0xFF00..0xFFFF are peripheral registers (Bus routes these)

# CPU / system block
MMIO_CAUSE = 0xFF00      # r   cause of the last exception entry
MMIO_TRAPARG = 0xFF01    # r   imm of last TRAP
MMIO_CYCLE_LO = 0xFF02   # r   cycle counter low 16
MMIO_CYCLE_HI = 0xFF03   # r   cycle counter high 16
MMIO_HALT = 0xFF04       # w   any write: halt machine (clean shutdown)
MMIO_FAULTPC = 0xFF05    # r   pc of last faulting instruction
# Timer: raises VEC_TIMER every PERIOD cycles while enabled
MMIO_TIMER_PERIOD = 0xFF10   # rw  cycles between ticks
MMIO_TIMER_CTRL = 0xFF11     # rw  bit0 = enable
MMIO_TIMER_TICKS = 0xFF12    # r   ticks fired (wraps)
# UART (character I/O to host console / dashboard)
MMIO_UART_TX = 0xFF20        # w   low 8 bits sent
MMIO_UART_RX = 0xFF21        # r   next byte, 0xFFFF if empty (read pops)
MMIO_UART_STATUS = 0xFF22    # r   bit0 = rx available
MMIO_UART_CTRL = 0xFF23      # rw  bit0 = rx irq enable
# GPIO
MMIO_GPIO_OUT = 0xFF30       # rw  8 LEDs
MMIO_GPIO_IN = 0xFF31        # r   4 buttons (bit set while held)
MMIO_GPIO_IRQEN = 0xFF32     # rw  bitmask: irq on press edge
# ADC (Q8.8 = degC * 256, signed)
MMIO_ADC_TEMP = 0xFF40       # r   tank temperature (noisy sensor)
MMIO_ADC_AMBIENT = 0xFF41    # r   ambient temperature
MMIO_ADC_SETPOINT = 0xFF42   # rw  setpoint knob (host moves it; firmware may write)
# PWM actuators (duty 0..255)
MMIO_PWM_HEATER = 0xFF50     # rw
MMIO_PWM_FAN = 0xFF51        # rw
# Watchdog: if enabled and not kicked within TIMEOUT*256 cycles -> VEC_WDOG
MMIO_WDOG_KICK = 0xFF60      # w   any write restarts the countdown
MMIO_WDOG_TIMEOUT = 0xFF61   # rw  units of 256 cycles; 0 = disabled

# Simulated clock. Plant and timer derive real time from cycles.
CLOCK_HZ = 100_000


def encode(op: str, rd: int = 0, rs: int = 0, imm: int = 0) -> tuple[int, int]:
    code, _ = OPCODES[op]
    return ((code << 8) | ((rd & 15) << 4) | (rs & 15)), imm & 0xFFFF


def decode(w0: int, w1: int) -> tuple[str | None, int, int, int]:
    """-> (name or None if illegal opcode, rd, rs, imm)."""
    return OPNAMES.get(w0 >> 8), (w0 >> 4) & 15, w0 & 15, w1


def mmio_constants() -> dict[str, int]:
    """Symbols the assembler predefines."""
    return {
        k: v
        for k, v in globals().items()
        if k.startswith(("MMIO_", "VEC_", "CAUSE_", "FLAG_"))
        or k in ("CODE_BASE", "RAM_TOP", "CLOCK_HZ", "ZERO_BASE")
    }
