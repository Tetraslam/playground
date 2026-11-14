# rtosaurus — plan

Coordinator: **agent 1** (`ses_e2794ac59ffeErNtUw5SylJLXo`).

An emulated 16-bit microcontroller (T16) running a **preemptive RTOS written in
its own assembly**. The firmware's tasks PID-control a simulated thermal plant
(a heated water tank with a fan, drifting ambient, a door that opens). Watch it
live, poke it over UART, move the setpoint, and **inject faults** (bit flips,
stuck sensors, IRQ storms) to see whether the kernel's fault handling and
watchdog keep the tank from boiling. A campaign mode runs many seeded fault
runs and reports survival curves.

Python 3.12, `uv run`. Package: `toys/rtosaurus/rtosaurus/`. Firmware sources:
`toys/rtosaurus/firmware/*.s`. Tests: `toys/rtosaurus/tests/`.

## Ownership

| agent | files | piece |
|---|---|---|
| 1 | `isa.py`, `machine.py`, `faults.py`, `cli.py`, `__main__.py`, `firmware/main.s`, README, `tests/test_integration.py`, pyproject | contract, wiring, fault injection, CLI, integration |
| 2 | `cpu.py`, `tests/test_cpu.py` | CPU core: decode/execute, flags, interrupts, faults |
| 3 | `asm.py`, `disasm.py`, `tests/test_asm.py` | assembler (+ `.include`, expressions, symbol map) and disassembler |
| 4 | `bus.py`, `tests/test_bus.py` | memory + MMIO bus + peripherals (timer, UART, GPIO, ADC, PWM, watchdog) |
| 5 | `plant.py`, `plots.py`, `tests/test_plant.py` | thermal plant physics + disturbances; matplotlib example plots |
| 6 | `firmware/kernel.s` | RTOS kernel: vectors, context switch, priority scheduler, syscalls, queues, fault + watchdog handlers |
| 7 | `firmware/lib.s`, `firmware/app.s` | firmware: PID control task, logger, UART shell, heartbeat/watchdog monitor, print helpers |
| 8 | `dash.py` | live terminal dashboard (textual) |

**`rtosaurus/isa.py` is the source of truth for the ISA and memory map. Read it
first.** Need a change? tell agent 1. Don't edit other agents' files.
Deps: `uv add --package rtosaurus <pkg>` from the repo root (tell agent 1).

## Python interfaces

```python
# isa.py (agent 1) — OPCODES, encode/decode, MMIO_* / VEC_* / CAUSE_* consts, CLOCK_HZ

# asm.py (agent 3)
@dataclass
class Image:
    words: dict[int, int]      # addr -> 16-bit word
    symbols: dict[str, int]    # every label and .equ (predefined isa constants may be omitted)
    lines: dict[int, str]      # instr addr -> "file:line  source" (for dash/disasm)
def assemble(src: str, path: str = "<src>", origin: int = isa.CODE_BASE) -> Image
def assemble_file(path: str) -> Image          # resolves .include relative to the including file
class AsmError(Exception): ...                 # message includes file:line
# disasm.py (agent 3)
def disasm(w0: int, w1: int, symbols: dict[str, int] | None = None) -> str

# bus.py (agent 4)
class Bus:
    def __init__(self, plant: "Plant | None" = None, seed: int = 0): ...
    mem: list[int]             # 65536 words (MMIO addresses are routed, not stored)
    cycles: int                # total cycles (CPU-visible via MMIO_CYCLE_*)
    cause: int; traparg: int; faultpc: int   # CPU sets these on exception entry
    halt_requested: bool
    uart_out: list[str]        # chars the firmware transmitted (append-only)
    def read(self, addr: int) -> int           # bad MMIO read -> raise BusError
    def write(self, addr: int, val: int) -> None   # bad MMIO write -> raise BusError
    def tick(self, cycles: int) -> None        # cycles += n; advance timer, watchdog, plant (dt = n/CLOCK_HZ)
    def pending_irq(self) -> int | None        # lowest pending vector among enabled sources
    def ack_irq(self, vec: int) -> None
    def uart_feed(self, text: str) -> None     # host -> firmware rx
    def press(self, button: int) -> None       # momentary press (edge irq if enabled)
    def load(self, words: dict[int, int]) -> None
class BusError(Exception): ...
# PWM writes set plant.heater / plant.fan = duty/255. ADC reads plant.read_temp() etc.
# converted to Q8.8 (round, clamp to int16, two's complement 16-bit).
# MMIO_ADC_SETPOINT write sets plant.setpoint; read returns it as Q8.8.

# cpu.py (agent 2)
class CPU:
    def __init__(self, bus: Bus): ...         # calls reset()
    regs: list[int]; pc: int; flags: int
    halted: bool; double_fault: bool
    def reset(self) -> None                    # regs zero, flags 0, pc = bus.mem[VEC_RESET]
    def step(self) -> int                      # take a pending IRQ (if I set) or execute 1 instr; returns cycles
                                               # BusError -> FAULT CAUSE_BUS. HALT or bus.halt_requested -> halted.
                                               # Does NOT call bus.tick (machine does).

# plant.py (agent 5)
class Plant:
    def __init__(self, seed: int = 0, time_scale: float = 60.0): ...  # plant-seconds per sim-second
    heater: float; fan: float                  # 0..1, set via bus PWM regs
    setpoint: float                            # degC, the knob
    sensor_override: float | None              # faults.py: stuck sensor value (None = normal)
    def step(self, dt: float) -> None          # dt in sim seconds
    def read_temp(self) -> float               # noisy sensor reading degC (honours sensor_override)
    def ambient(self) -> float
    def state(self) -> dict                    # t, temp, ambient, heater, fan, setpoint, door_open, boiled

# machine.py (agent 1)
class Machine:
    def __init__(self, image: Image | None = None, seed: int = 0, plant: Plant | None = None): ...
    bus; cpu; plant; image
    def step(self) -> int; def run(self, cycles: int) -> None
    def tasks(self) -> list[dict]              # decoded kernel TCBs via image.symbols["k_tcb"]
    trace: list[dict]                          # periodic samples: t, temp, setpoint, heater, fan, task, events
    def uart_text(self) -> str
def build_firmware() -> Image                  # assembles firmware/main.s
```

## Assembler syntax (agent 3 implements, agents 6/7 write against it)

- one statement per line, `;` comments, case-insensitive mnemonics/registers
- `label:` (may share a line with an instruction); labels are global
- operands: `r0..r7`, `sp`; immediates: `42`, `-3`, `0x1F`, `0b101`, `'a'`,
  `'\n'`, symbols, and `+ - * / & | << >> ( )` expressions over them
- memory: `LD r1, [r2+4]`, `LD r1, [MMIO_ADC_TEMP]`, `ST [r2-1], r3`
- directives: `.org addr`, `.word e1, e2, ...`, `.zero n`, `.string "hi\n"`
  (one char per word, 0-terminated), `.equ NAME, expr`, `.include "file.s"`
- every name from `isa.mmio_constants()` is predefined
- forward references allowed (two-pass); duplicate labels are errors

## Firmware layout + kernel ABI (agents 6 & 7)

`firmware/main.s` (agent 1):

```
.include "kernel.s"   ; .org 0: vector table, then kernel code/data
.include "lib.s"
.include "app.s"
```

Kernel (agent 6) owns the vector table at 0..15 (`.org 0` + `.word reset, ...`)
and `reset`. On reset it: sets sp to a kernel stack, calls `app_init` (interrupts
off), builds TCBs from `task_table`, programs the timer (period **1000 cycles =
100 Hz tick**), enables the UART rx irq, `EI`, starts the highest-priority ready task.
Task stacks: kernel carves them downward from `RAM_TOP` per `stack_words`.

App (agent 7) must define:

- `app_init:` (subroutine, may just `RET`)
- `task_table:` entries of 3 words `entry, priority, stack_words`, terminated
  by a `0` word. Higher priority number wins; equal priority round-robins each
  tick. Max 8 app tasks. Kernel adds its own idle task (priority 0) at index 8.
  Returning from a task entry = exit.

Kernel symbols the dashboard/machine read (keep names + layout):

- `k_tcb`: 9 TCBs (8 app + idle at index 8), 6 words each:
  `state, priority, saved_sp, wake_tick, entry, faults`
  states: `0 free, 1 ready, 2 running, 3 sleeping, 4 blocked_send, 5 blocked_recv, 6 dead`
- `k_current`: index of running task. `k_ticks`: tick counter.

Syscalls: `LDI r0, n` + args in `r1, r2`, then `TRAP 0`. Result in `r0`;
r1..r6 preserved.

| n | name | args | result |
|---|---|---|---|
| 0 | yield | | |
| 1 | sleep | r1 = ticks | |
| 2 | ticks | | r0 = k_ticks |
| 3 | putc | r1 = char | |
| 4 | send | r1 = queue (0..7), r2 = value | blocks while full (depth 8) |
| 5 | recv | r1 = queue | r0 = value, blocks while empty |
| 6 | exit | | task becomes dead |
| 7 | task_id | | r0 = own index |

Queue 7 is the UART rx queue: the kernel's UART ISR pushes received bytes into
it (drops when full). Queues 0..6 are free for the app.

Faults (`VEC_FAULT`): kernel marks the current task dead, increments its
`faults`, prints `!fault t<id> c<cause hex> pc<faultpc hex>\n` over UART, and
schedules the next task. Fault in kernel/idle → `HALT`.
Watchdog (`VEC_WDOG`): kernel prints `!wdog\n` and jumps to `reset` (full
firmware restart). App policy (agent 7): a monitor task kicks it only when the
control task has checked in recently; timeout ~0.5 s sim.

App behaviour (agent 7): control task every 10 ticks reads `MMIO_ADC_TEMP` and
`MMIO_ADC_SETPOINT`, runs a Q8.8 PID (FMUL, with anti-windup), writes
`MMIO_PWM_HEATER`, turns the fan on when > setpoint + 3 °C, sends telemetry on
queue 0. Logger task prints `T=41.25 S=45.00 H=180 F=0\n` lines (every ~1 s).
Shell task reads queue 7: `s45\n` sets the setpoint, `p\n` prints the task
table, `?\n` help. Heartbeat blinks LED0; LED7 = overheat alarm (> 90 °C:
heater forced off).

## Plant (agent 5)

Thermal tank (~20 L water), heater up to ~3 kW, losses to ambient (fan
multiplies the loss coefficient), ambient drifts sinusoidally (day/night) plus
a door that randomly opens (big loss spike). Sensor noise. `time_scale`
(default 60) compresses physics so a run is watchable (sim at 100 kHz runs
maybe 2-5x slower than real time in Python). `boiled` once temp >= 100.
Deterministic per seed.

`plots.py`: `plot_run(trace, out_png, title="")` (temp/setpoint/heater/fan vs
time + fault/event markers), `plot_gantt(trace, out_png)` (which task ran
when), `plot_campaign(results, out_png)` (survival vs fault rate). Matplotlib.
Trace sample dict keys: `t` (sim s), `plant_t` (plant s), `temp`, `setpoint`,
`heater`, `fan`, `task` (k_current or None), `events` (list of str, e.g.
`"fault t1"`, `"wdog"`, `"inject ram-flip 0x0123"`).

## Faults + CLI (agent 1)

`faults.py`: seeded injectors: RAM bit flip (code/data/stack), register bit
flip, stuck sensor, IRQ storm. `uv run python -m rtosaurus run|dash|campaign|asm|disasm`.

## Tests

`uv run pytest toys/rtosaurus` — ship tests for your module.
Firmware agents: until machine.py lands, assemble with asm.py and run with a
tiny harness; afterwards `uv run python -m rtosaurus run --cycles 200000`.

## Process

Sign `agent N`. Tell agent 1 when your piece works (with the test command).
Interface questions → agent 1. Commit: `claim("playground-git")`, add only
your own files, `git pull --rebase`, push, release (minutes 0). Never touch
`toys/coreloom/warriors/evolved_s1.red`.
