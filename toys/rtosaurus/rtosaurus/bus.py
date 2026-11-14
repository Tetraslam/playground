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
  latch the NMI once. `pending_nmi()` reports it (never `pending_irq()`); the CPU
  takes VEC_WDOG regardless of I and calls `ack_irq(VEC_WDOG)`, which clears the
  latch and leaves the watchdog disarmed until firmware kicks it or rewrites
  TIMEOUT (the kernel's reset path does), so a dead firmware can't NMI-storm

Speed: `tick()` is one add and one compare against the nearest deadline (timer,
watchdog, next plant step); peripheral work only happens when one is crossed.
The pending vector is cached in `bus.irq` and recomputed only when an interrupt
source changes, so `pending_irq()` is an attribute read (likewise `bus.nmi` for `pending_nmi()`). RAM reads/writes take
a single branch; MMIO dispatches through per-address handler tables. A hot
loop may read `bus.irq` and index `bus.mem` directly for addresses < MMIO_BASE.
The plant is stepped in PLANT_STEP_CYCLES chunks (dt = cycles / CLOCK_HZ).
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


NEVER = 1 << 62  # deadline sentinel


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
        self._timer_next = NEVER
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
        self._wdog_next = NEVER
        # plant
        self._plant_last = 0
        self._plant_next = PLANT_STEP_CYCLES if plant is not None else NEVER
        # interrupts
        self._timer_pending = False
        self.nmi = False  # watchdog NMI latch; hot loops may read it directly
        self.forced: set[int] = set()  # faults.py: IRQ storms latch vectors here
        self.irq: int | None = None  # cached lowest pending vector
        self.irq_taken: dict[int, int] = {}
        self._next_event = NEVER
        self._reschedule()

        self._rd = {
            isa.MMIO_CAUSE: lambda: self.cause,
            isa.MMIO_TRAPARG: lambda: self.traparg,
            isa.MMIO_CYCLE_LO: lambda: self.cycles & MASK,
            isa.MMIO_CYCLE_HI: lambda: (self.cycles >> 16) & MASK,
            isa.MMIO_FAULTPC: lambda: self.faultpc,
            isa.MMIO_TIMER_PERIOD: lambda: self.timer_period,
            isa.MMIO_TIMER_CTRL: lambda: self.timer_ctrl,
            isa.MMIO_TIMER_TICKS: lambda: self.timer_ticks,
            isa.MMIO_UART_RX: self._rx_pop,
            isa.MMIO_UART_STATUS: lambda: 1 if self.uart_rx else 0,
            isa.MMIO_UART_CTRL: lambda: self.uart_ctrl,
            isa.MMIO_GPIO_OUT: lambda: self.gpio_out,
            isa.MMIO_GPIO_IN: self.buttons_held,
            isa.MMIO_GPIO_IRQEN: lambda: self.gpio_irqen,
            isa.MMIO_ADC_TEMP: self._adc_temp,
            isa.MMIO_ADC_AMBIENT: self._adc_ambient,
            isa.MMIO_ADC_SETPOINT: lambda: to_q88(self.setpoint),
            isa.MMIO_PWM_HEATER: lambda: self.pwm_heater,
            isa.MMIO_PWM_FAN: lambda: self.pwm_fan,
            isa.MMIO_WDOG_TIMEOUT: lambda: self.wdog_timeout,
        }
        self._wr = {
            isa.MMIO_HALT: self._w_halt,
            isa.MMIO_TIMER_PERIOD: self._w_timer_period,
            isa.MMIO_TIMER_CTRL: self._w_timer_ctrl,
            isa.MMIO_UART_TX: self._w_uart_tx,
            isa.MMIO_UART_CTRL: self._w_uart_ctrl,
            isa.MMIO_GPIO_OUT: self._w_gpio_out,
            isa.MMIO_GPIO_IRQEN: self._w_gpio_irqen,
            isa.MMIO_ADC_SETPOINT: self._w_setpoint,
            isa.MMIO_PWM_HEATER: self._w_heater,
            isa.MMIO_PWM_FAN: self._w_fan,
            isa.MMIO_WDOG_KICK: self._w_kick,
            isa.MMIO_WDOG_TIMEOUT: self._w_wdog_timeout,
        }

    # ---- memory ---------------------------------------------------------
    def read(self, addr: int) -> int:
        if 0 <= addr < 0xFF00:  # isa.MMIO_BASE, inlined
            return self.mem[addr]
        addr &= MASK
        if addr < isa.MMIO_BASE:
            return self.mem[addr]
        h = self._rd.get(addr)
        if h is None:
            why = "write-only register" if addr in self._wr else "unmapped"
            raise BusError(addr, False, why)
        return h() & MASK

    def write(self, addr: int, val: int) -> None:
        if 0 <= addr < 0xFF00:  # isa.MMIO_BASE, inlined
            self.mem[addr] = val & MASK
            return
        addr &= MASK
        val &= MASK
        if addr < isa.MMIO_BASE:
            self.mem[addr] = val
            return
        h = self._wr.get(addr)
        if h is None:
            why = "read-only register" if addr in self._rd else "unmapped"
            raise BusError(addr, True, why)
        h(val)

    def load(self, words: dict[int, int]) -> None:
        for addr, w in words.items():
            if not 0 <= addr < isa.MMIO_BASE:
                raise ValueError(f"image word at 0x{addr:04X} outside RAM")
            self.mem[addr] = w & MASK

    # ---- MMIO handlers --------------------------------------------------
    def _rx_pop(self) -> int:
        if not self.uart_rx:
            return 0xFFFF
        v = self.uart_rx.popleft()
        if not self.uart_rx:
            self._update_irq()
        return v

    def _adc_temp(self) -> int:
        return to_q88(self.plant.read_temp() if self.plant is not None else DEFAULT_TEMP)

    def _adc_ambient(self) -> int:
        return to_q88(self.plant.ambient() if self.plant is not None else DEFAULT_TEMP)

    def _w_halt(self, v: int) -> None:
        self.halt_requested = True

    def _w_timer_period(self, v: int) -> None:
        self.timer_period = v
        self._arm_timer()

    def _w_timer_ctrl(self, v: int) -> None:
        was = self.timer_ctrl
        self.timer_ctrl = v & 1
        if self.timer_ctrl != was:
            self._arm_timer()

    def _arm_timer(self) -> None:
        on = self.timer_ctrl & 1 and self.timer_period
        self._timer_next = self.cycles + self.timer_period if on else NEVER
        self._reschedule()

    def _w_uart_tx(self, v: int) -> None:
        self.uart_out.append(chr(v & 0xFF))

    def _w_uart_ctrl(self, v: int) -> None:
        self.uart_ctrl = v & 1
        self._update_irq()

    def _w_gpio_out(self, v: int) -> None:
        self.gpio_out = v & 0xFF

    def _w_gpio_irqen(self, v: int) -> None:
        self.gpio_irqen = v & ((1 << NUM_BUTTONS) - 1)
        self._update_irq()

    def _w_setpoint(self, v: int) -> None:
        self.setpoint = from_q88(v)

    def _w_heater(self, v: int) -> None:
        self.pwm_heater = _duty(v)
        if self.plant is not None:
            self.plant.heater = self.pwm_heater / 255

    def _w_fan(self, v: int) -> None:
        self.pwm_fan = _duty(v)
        if self.plant is not None:
            self.plant.fan = self.pwm_fan / 255

    def _w_kick(self, v: int) -> None:
        self._arm_wdog()

    def _w_wdog_timeout(self, v: int) -> None:
        self.wdog_timeout = v
        self._arm_wdog()

    def _arm_wdog(self) -> None:
        t = self.wdog_timeout
        self._wdog_next = self.cycles + t * 256 if t else NEVER
        self._reschedule()

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
        c = self.cycles + cycles
        self.cycles = c
        if c >= self._next_event:
            self._service()

    def _service(self) -> None:
        c = self.cycles
        if c >= self._timer_next:
            p = self.timer_period
            fired = 1 + (c - self._timer_next) // p
            self.timer_ticks = (self.timer_ticks + fired) & MASK
            self._timer_next += fired * p
            self._timer_pending = True
        if c >= self._wdog_next:
            self.nmi = True
            self._wdog_next = NEVER  # fires once until re-armed
        if c >= self._plant_next:
            self.plant.step((c - self._plant_last) / isa.CLOCK_HZ)
            self._plant_last = c
            self._plant_next = c + PLANT_STEP_CYCLES
        self._reschedule()
        self._update_irq()

    def _reschedule(self) -> None:
        self._next_event = min(self._timer_next, self._wdog_next, self._plant_next)

    # ---- interrupts -----------------------------------------------------
    def _update_irq(self) -> None:
        if self._timer_pending:
            v = isa.VEC_TIMER
        elif self.uart_rx and self.uart_ctrl & 1:
            v = isa.VEC_UART
        elif self._gpio_edge & self.gpio_irqen:
            v = isa.VEC_GPIO
        else:
            v = None
        if self.forced:
            f = min(self.forced)
            v = f if v is None else min(v, f)
        self.irq = v

    def pending_nmi(self) -> bool:
        """Watchdog expired: CPU takes VEC_WDOG even with I clear."""
        return self.nmi

    def pending_irq(self) -> int | None:
        """Lowest pending vector among enabled sources (CPU checks the I flag)."""
        return self.irq

    def ack_irq(self, vec: int) -> None:
        self.irq_taken[vec] = self.irq_taken.get(vec, 0) + 1
        if vec in self.forced:
            self.forced.discard(vec)
        elif vec == isa.VEC_TIMER:
            self._timer_pending = False
        elif vec == isa.VEC_GPIO:
            self._gpio_edge &= ~self.gpio_irqen
        elif vec == isa.VEC_WDOG:
            self.nmi = False
        # VEC_UART is level-triggered: clears when the ISR drains rx.
        self._update_irq()

    def raise_irq(self, vec: int) -> None:
        """Spuriously latch an interrupt (fault injection: IRQ storms)."""
        self.forced.add(vec)
        self._update_irq()

    # ---- host side ------------------------------------------------------
    def uart_feed(self, text: str) -> None:
        self.uart_rx.extend(ord(c) & 0xFF for c in text)
        self._update_irq()

    def uart_text(self) -> str:
        return "".join(self.uart_out)

    def press(self, button: int) -> None:
        if not 0 <= button < NUM_BUTTONS:
            raise ValueError(f"button {button} out of range 0..{NUM_BUTTONS - 1}")
        self._button_until[button] = self.cycles + BUTTON_HOLD_CYCLES
        self._gpio_edge |= 1 << button
        self._update_irq()

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
            "wdog_nmi": self.nmi,
            "wdog_left": None if self._wdog_next == NEVER else self._wdog_next - self.cycles,
            "uart_rx_pending": len(self.uart_rx),
            "irq_taken": dict(self.irq_taken),
        }
