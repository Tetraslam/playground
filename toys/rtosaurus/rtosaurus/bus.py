"""T16 memory + MMIO bus + peripherals (owner: agent 4).

RAM is a flat list of 65536 words. Addresses at or above `MMIO_BASE` never touch
`mem`; they route to peripheral registers below. Unknown MMIO addresses, reads of
write-only registers, and writes to read-only registers raise `BusError` (the CPU
turns that into a FAULT with CAUSE_BUS).

Peripherals, all advanced by `tick(cycles)`:

- timer: fires VEC_TIMER every PERIOD cycles while enabled (edge, cleared by ack)
- UART: tx appends to `uart_out`; rx is a host-fed FIFO. VEC_UART is level
  triggered: pending while rx has data and the rx irq is enabled, so the ISR
  must drain it (ack is a no-op)
- GPIO: 8 LEDs out, 4 buttons in; `press()` holds a button for
  BUTTON_HOLD_CYCLES and latches a press edge (VEC_GPIO if enabled in IRQEN)
- ADC: plant temperature / ambient / setpoint as signed Q8.8
- PWM: heater / fan duty 0..255 (written value read as signed, clamped), pushed
  into the plant as duty/255
- watchdog: if TIMEOUT != 0 and nobody writes KICK within TIMEOUT*256 cycles,
  latch VEC_WDOG once (re-armed by a kick or a TIMEOUT write)

The plant is stepped in PLANT_STEP_CYCLES chunks (dt = cycles / CLOCK_HZ) so
per-instruction ticks stay cheap.
"""

from __future__ import annotations

import random
from collections import deque
from typing import TYPE_CHECKING

from rtosaurus import isa

if TYPE_CHECKING:  # pragma: no cover
    from rtosaurus.plant import Plant

MASK = 0xFFFF
PLANT_STEP_CYCLES = 100  # 1 ms of sim time per plant step
BUTTON_HOLD_CYCLES = 2_000  # 20 ms: how long a momentary press reads as held
NUM_BUTTONS = 4
DEFAULT_TEMP = 20.0  # used when no plant is attached


class BusError(Exception):
    """Bad MMIO access. `addr` is the offending address, `write` the direction."""

    def __init__(self, addr: int, write: bool, why: str = ""):
        self.addr = addr & MASK
        self.write = write
        kind = "write" if write else "read"
        super().__init__(f"bus {kind} 0x{self.addr:04X}" + (f": {why}" if why else ""))


def to_q88(x: float) -> int:
    """degC -> signed Q8.8, rounded, clamped to int16, as a 16-bit word."""
    v = round(x * 256)
    v = max(-32768, min(32767, v))
    return v & MASK


def from_q88(w: int) -> float:
    w &= MASK
    return (w - 0x10000 if w & 0x8000 else w) / 256


def _signed(w: int) -> int:
    w &= MASK
    return w - 0x10000 if w & 0x8000 else w


def _duty(w: int) -> int:
    return max(0, min(255, _signed(w)))


# Register access tables. Anything in MMIO space not listed is unmapped.
_READABLE = {
    isa.MMIO_CAUSE, isa.MMIO_TRAPARG, isa.MMIO_CYCLE_LO, isa.MMIO_CYCLE_HI,
    isa.MMIO_FAULTPC,
    isa.MMIO_TIMER_PERIOD, isa.MMIO_TIMER_CTRL, isa.MMIO_TIMER_TICKS,
    isa.MMIO_UART_RX, isa.MMIO_UART_STATUS, isa.MMIO_UART_CTRL,
    isa.MMIO_GPIO_OUT, isa.MMIO_GPIO_IN, isa.MMIO_GPIO_IRQEN,
    isa.MMIO_ADC_TEMP, isa.MMIO_ADC_AMBIENT, isa.MMIO_ADC_SETPOINT,
    isa.MMIO_PWM_HEATER, isa.MMIO_PWM_FAN,
    isa.MMIO_WDOG_TIMEOUT,
}  # fmt: skip
_WRITABLE = {
    isa.MMIO_HALT,
    isa.MMIO_TIMER_PERIOD, isa.MMIO_TIMER_CTRL,
    isa.MMIO_UART_TX, isa.MMIO_UART_CTRL,
    isa.MMIO_GPIO_OUT, isa.MMIO_GPIO_IRQEN,
    isa.MMIO_ADC_SETPOINT,
    isa.MMIO_PWM_HEATER, isa.MMIO_PWM_FAN,
    isa.MMIO_WDOG_KICK, isa.MMIO_WDOG_TIMEOUT,
}  # fmt: skip


class Bus:
    def __init__(self, plant: Plant | None = None, seed: int = 0):
        self.plant = plant
        self.seed = seed
        self.rng = random.Random(seed)
        self.mem: list[int] = [0] * 0x10000
        self.cycles = 0
        # CPU-written exception info
        self.cause = 0
        self.traparg = 0
        self.faultpc = 0
        self.halt_requested = False
        # timer
        self.timer_period = 0
        self.timer_ctrl = 0
        self.timer_ticks = 0
        self._timer_count = 0
        # UART
        self.uart_out: list[str] = []
        self.uart_rx: deque[int] = deque()
        self.uart_ctrl = 0
        # GPIO
        self.gpio_out = 0
        self.gpio_irqen = 0
        self._button_until = [0] * NUM_BUTTONS  # cycle at which each button releases
        self._gpio_edge = 0  # latched press edges (bitmask)
        # ADC / PWM
        self._setpoint = plant.setpoint if plant is not None else 45.0
        self.pwm_heater = 0
        self.pwm_fan = 0
        # watchdog
        self.wdog_timeout = 0
        self._wdog_count = 0
        self._wdog_armed = True
        # irq lines (edge-latched sources)
        self._timer_pending = False
        self._wdog_pending = False
        self.forced: set[int] = set()  # faults.py: IRQ storms latch vectors here
        # stats
        self.irq_taken: dict[int, int] = {}
        self._plant_acc = 0

    # ---- memory ---------------------------------------------------------
    def read(self, addr: int) -> int:
        addr &= MASK
        if addr < isa.MMIO_BASE:
            return self.mem[addr]
        if addr not in _READABLE:
            why = "write-only register" if addr in _WRITABLE else "unmapped"
            raise BusError(addr, False, why)
        return self._mmio_read(addr) & MASK

    def write(self, addr: int, val: int) -> None:
        addr &= MASK
        val &= MASK
        if addr < isa.MMIO_BASE:
            self.mem[addr] = val
            return
        if addr not in _WRITABLE:
            why = "read-only register" if addr in _READABLE else "unmapped"
            raise BusError(addr, True, why)
        self._mmio_write(addr, val)

    def load(self, words: dict[int, int]) -> None:
        for addr, w in words.items():
            if not 0 <= addr < isa.MMIO_BASE:
                raise ValueError(f"image word at 0x{addr:04X} outside RAM")
            self.mem[addr] = w & MASK

    # ---- MMIO -----------------------------------------------------------
    def _mmio_read(self, a: int) -> int:
        if a == isa.MMIO_CAUSE:
            return self.cause
        if a == isa.MMIO_TRAPARG:
            return self.traparg
        if a == isa.MMIO_CYCLE_LO:
            return self.cycles & MASK
        if a == isa.MMIO_CYCLE_HI:
            return (self.cycles >> 16) & MASK
        if a == isa.MMIO_FAULTPC:
            return self.faultpc
        if a == isa.MMIO_TIMER_PERIOD:
            return self.timer_period
        if a == isa.MMIO_TIMER_CTRL:
            return self.timer_ctrl
        if a == isa.MMIO_TIMER_TICKS:
            return self.timer_ticks & MASK
        if a == isa.MMIO_UART_RX:
            return self.uart_rx.popleft() if self.uart_rx else 0xFFFF
        if a == isa.MMIO_UART_STATUS:
            return 1 if self.uart_rx else 0
        if a == isa.MMIO_UART_CTRL:
            return self.uart_ctrl
        if a == isa.MMIO_GPIO_OUT:
            return self.gpio_out
        if a == isa.MMIO_GPIO_IN:
            return self.buttons_held()
        if a == isa.MMIO_GPIO_IRQEN:
            return self.gpio_irqen
        if a == isa.MMIO_ADC_TEMP:
            t = self.plant.read_temp() if self.plant is not None else DEFAULT_TEMP
            return to_q88(t)
        if a == isa.MMIO_ADC_AMBIENT:
            t = self.plant.ambient() if self.plant is not None else DEFAULT_TEMP
            return to_q88(t)
        if a == isa.MMIO_ADC_SETPOINT:
            return to_q88(self.setpoint)
        if a == isa.MMIO_PWM_HEATER:
            return self.pwm_heater
        if a == isa.MMIO_PWM_FAN:
            return self.pwm_fan
        if a == isa.MMIO_WDOG_TIMEOUT:
            return self.wdog_timeout
        raise BusError(a, False, "unmapped")  # pragma: no cover

    def _mmio_write(self, a: int, v: int) -> None:
        if a == isa.MMIO_HALT:
            self.halt_requested = True
        elif a == isa.MMIO_TIMER_PERIOD:
            self.timer_period = v
            self._timer_count = 0
        elif a == isa.MMIO_TIMER_CTRL:
            if (v & 1) and not (self.timer_ctrl & 1):
                self._timer_count = 0
            self.timer_ctrl = v & 1
        elif a == isa.MMIO_UART_TX:
            self.uart_out.append(chr(v & 0xFF))
        elif a == isa.MMIO_UART_CTRL:
            self.uart_ctrl = v & 1
        elif a == isa.MMIO_GPIO_OUT:
            self.gpio_out = v & 0xFF
        elif a == isa.MMIO_GPIO_IRQEN:
            self.gpio_irqen = v & ((1 << NUM_BUTTONS) - 1)
        elif a == isa.MMIO_ADC_SETPOINT:
            self.setpoint = from_q88(v)
        elif a == isa.MMIO_PWM_HEATER:
            self.pwm_heater = _duty(v)
            if self.plant is not None:
                self.plant.heater = self.pwm_heater / 255
        elif a == isa.MMIO_PWM_FAN:
            self.pwm_fan = _duty(v)
            if self.plant is not None:
                self.plant.fan = self.pwm_fan / 255
        elif a == isa.MMIO_WDOG_KICK:
            self._wdog_count = 0
            self._wdog_armed = True
        elif a == isa.MMIO_WDOG_TIMEOUT:
            self.wdog_timeout = v
            self._wdog_count = 0
            self._wdog_armed = True

    # ---- setpoint is shared with the plant ------------------------------
    @property
    def setpoint(self) -> float:
        return self.plant.setpoint if self.plant is not None else self._setpoint

    @setpoint.setter
    def setpoint(self, val: float) -> None:
        if self.plant is not None:
            self.plant.setpoint = val
        self._setpoint = val

    # ---- time -----------------------------------------------------------
    def tick(self, cycles: int) -> None:
        if cycles <= 0:
            return
        self.cycles += cycles

        if self.timer_ctrl & 1 and self.timer_period:
            self._timer_count += cycles
            if self._timer_count >= self.timer_period:
                fired, self._timer_count = divmod(self._timer_count, self.timer_period)
                self.timer_ticks = (self.timer_ticks + fired) & MASK
                self._timer_pending = True

        if self.wdog_timeout and self._wdog_armed:
            self._wdog_count += cycles
            if self._wdog_count >= self.wdog_timeout * 256:
                self._wdog_pending = True
                self._wdog_armed = False

        if self.plant is not None:
            self._plant_acc += cycles
            if self._plant_acc >= PLANT_STEP_CYCLES:
                self.plant.step(self._plant_acc / isa.CLOCK_HZ)
                self._plant_acc = 0

    # ---- interrupts -----------------------------------------------------
    def pending_irq(self) -> int | None:
        """Lowest pending vector among enabled sources (CPU checks the I flag)."""
        if self._timer_pending:
            return isa.VEC_TIMER
        if self.uart_rx and self.uart_ctrl & 1:
            return isa.VEC_UART
        if self._gpio_edge & self.gpio_irqen:
            return isa.VEC_GPIO
        if self._wdog_pending:
            return isa.VEC_WDOG
        if self.forced:
            return min(self.forced)
        return None

    def ack_irq(self, vec: int) -> None:
        self.irq_taken[vec] = self.irq_taken.get(vec, 0) + 1
        if vec in self.forced:
            self.forced.discard(vec)
            return
        if vec == isa.VEC_TIMER:
            self._timer_pending = False
        elif vec == isa.VEC_GPIO:
            self._gpio_edge &= ~self.gpio_irqen
        elif vec == isa.VEC_WDOG:
            self._wdog_pending = False
        # VEC_UART is level-triggered: clears when the ISR drains rx.

    def raise_irq(self, vec: int) -> None:
        """Spuriously latch an interrupt (fault injection: IRQ storms)."""
        self.forced.add(vec)

    # ---- host side ------------------------------------------------------
    def uart_feed(self, text: str) -> None:
        self.uart_rx.extend(ord(c) & 0xFF for c in text)

    def uart_text(self) -> str:
        return "".join(self.uart_out)

    def press(self, button: int) -> None:
        if not 0 <= button < NUM_BUTTONS:
            raise ValueError(f"button {button} out of range 0..{NUM_BUTTONS - 1}")
        self._button_until[button] = self.cycles + BUTTON_HOLD_CYCLES
        self._gpio_edge |= 1 << button

    def buttons_held(self) -> int:
        return sum(1 << i for i, t in enumerate(self._button_until) if self.cycles < t)

    def leds(self) -> list[bool]:
        return [bool(self.gpio_out >> i & 1) for i in range(8)]

    def snapshot(self) -> dict:
        """Peripheral state for dashboards/traces."""
        return {
            "cycles": self.cycles,
            "timer_ticks": self.timer_ticks,
            "leds": self.gpio_out,
            "heater": self.pwm_heater,
            "fan": self.pwm_fan,
            "setpoint": self.setpoint,
            "wdog_timeout": self.wdog_timeout,
            "wdog_left": (
                max(0, self.wdog_timeout * 256 - self._wdog_count)
                if self.wdog_timeout and self._wdog_armed
                else None
            ),
            "uart_rx_pending": len(self.uart_rx),
            "irq_taken": dict(self.irq_taken),
        }
