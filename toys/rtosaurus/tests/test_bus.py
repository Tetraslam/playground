import pytest
from rtosaurus import isa
from rtosaurus.bus import BUTTON_HOLD_CYCLES, Bus, BusError, from_q88, to_q88


class FakePlant:
    def __init__(self):
        self.heater = 0.0
        self.fan = 0.0
        self.setpoint = 45.0
        self.sensor_override = None
        self.temp = 21.5
        self.dt_total = 0.0

    def step(self, dt):
        self.dt_total += dt

    def read_temp(self):
        return self.temp if self.sensor_override is None else self.sensor_override

    def ambient(self):
        return -3.25


def test_ram_roundtrip_and_wrap():
    b = Bus()
    b.write(0x1234, 0x1_ABCD)
    assert b.read(0x1234) == 0xABCD
    b.write(0x1_0005, 7)  # addresses wrap to 16 bits
    assert b.read(5) == 7


def test_load_rejects_mmio():
    b = Bus()
    b.load({0x10: 0xFFFF1, 0x11: 2})
    assert b.mem[0x10] == 0xFFF1
    with pytest.raises(ValueError):
        b.load({isa.MMIO_BASE: 1})


def test_bad_mmio_raises():
    b = Bus()
    with pytest.raises(BusError):
        b.read(0xFFEE)  # unmapped
    with pytest.raises(BusError):
        b.write(isa.MMIO_ADC_TEMP, 1)  # read-only
    with pytest.raises(BusError):
        b.read(isa.MMIO_UART_TX)  # write-only
    with pytest.raises(BusError):
        b.write(isa.MMIO_CYCLE_LO, 0)


def test_mmio_never_touches_mem():
    b = Bus()
    b.write(isa.MMIO_GPIO_OUT, 0x1A5)
    assert b.mem[isa.MMIO_GPIO_OUT] == 0
    assert b.read(isa.MMIO_GPIO_OUT) == 0xA5
    assert b.leds()[0] and b.leds()[2] and not b.leds()[1]


def test_cycle_counter_and_exception_regs():
    b = Bus()
    b.tick(0x1_0003)
    assert b.read(isa.MMIO_CYCLE_LO) == 3
    assert b.read(isa.MMIO_CYCLE_HI) == 1
    b.cause, b.traparg, b.faultpc = isa.CAUSE_DIV0, 9, 0x40
    assert b.read(isa.MMIO_CAUSE) == isa.CAUSE_DIV0
    assert b.read(isa.MMIO_TRAPARG) == 9
    assert b.read(isa.MMIO_FAULTPC) == 0x40


def test_halt():
    b = Bus()
    assert not b.halt_requested
    b.write(isa.MMIO_HALT, 0)
    assert b.halt_requested


def test_timer_fires_every_period():
    b = Bus()
    b.write(isa.MMIO_TIMER_PERIOD, 1000)
    b.tick(5000)
    assert b.pending_irq() is None  # not enabled yet
    b.write(isa.MMIO_TIMER_CTRL, 1)
    b.tick(999)
    assert b.pending_irq() is None
    b.tick(1)
    assert b.pending_irq() == isa.VEC_TIMER
    b.ack_irq(isa.VEC_TIMER)
    assert b.pending_irq() is None
    b.tick(2500)
    assert b.read(isa.MMIO_TIMER_TICKS) == 3
    assert b.pending_irq() == isa.VEC_TIMER


def test_uart_tx_rx_level_irq():
    b = Bus()
    for c in "hi\n":
        b.write(isa.MMIO_UART_TX, ord(c) | 0x300)
    assert b.uart_text() == "hi\n"
    assert b.read(isa.MMIO_UART_RX) == 0xFFFF
    b.uart_feed("ab")
    assert b.read(isa.MMIO_UART_STATUS) == 1
    assert b.pending_irq() is None  # rx irq disabled
    b.write(isa.MMIO_UART_CTRL, 1)
    assert b.pending_irq() == isa.VEC_UART
    b.ack_irq(isa.VEC_UART)
    assert b.pending_irq() == isa.VEC_UART  # level: still has data
    assert b.read(isa.MMIO_UART_RX) == ord("a")
    assert b.read(isa.MMIO_UART_RX) == ord("b")
    assert b.read(isa.MMIO_UART_STATUS) == 0
    assert b.pending_irq() is None


def test_gpio_press_edge_and_hold():
    b = Bus()
    b.press(2)
    assert b.read(isa.MMIO_GPIO_IN) == 0b100
    assert b.pending_irq() is None  # not enabled
    b.write(isa.MMIO_GPIO_IRQEN, 0b100)
    assert b.pending_irq() == isa.VEC_GPIO
    b.ack_irq(isa.VEC_GPIO)
    assert b.pending_irq() is None
    b.tick(BUTTON_HOLD_CYCLES)
    assert b.read(isa.MMIO_GPIO_IN) == 0
    with pytest.raises(ValueError):
        b.press(4)


def test_q88():
    assert to_q88(1.0) == 0x0100
    assert to_q88(-1.5) == 0xFE80
    assert to_q88(1000.0) == 0x7FFF
    assert to_q88(-1000.0) == 0x8000
    assert from_q88(0xFE80) == -1.5


def test_adc_and_pwm_drive_plant():
    p = FakePlant()
    b = Bus(plant=p)
    assert b.read(isa.MMIO_ADC_TEMP) == to_q88(21.5)
    assert from_q88(b.read(isa.MMIO_ADC_AMBIENT)) == -3.25
    p.sensor_override = 99.0
    assert from_q88(b.read(isa.MMIO_ADC_TEMP)) == 99.0
    assert from_q88(b.read(isa.MMIO_ADC_SETPOINT)) == 45.0
    b.write(isa.MMIO_ADC_SETPOINT, to_q88(60.25))
    assert p.setpoint == 60.25
    p.setpoint = 50.0  # host knob moves
    assert from_q88(b.read(isa.MMIO_ADC_SETPOINT)) == 50.0

    b.write(isa.MMIO_PWM_HEATER, 255)
    assert p.heater == 1.0
    b.write(isa.MMIO_PWM_FAN, 1000)  # clamps
    assert p.fan == 1.0 and b.read(isa.MMIO_PWM_FAN) == 255
    b.write(isa.MMIO_PWM_HEATER, -5)  # negative clamps to off, not full blast
    assert p.heater == 0.0 and b.read(isa.MMIO_PWM_HEATER) == 0


def test_no_plant_defaults():
    b = Bus()
    assert from_q88(b.read(isa.MMIO_ADC_TEMP)) == 20.0
    b.write(isa.MMIO_ADC_SETPOINT, to_q88(30))
    assert b.setpoint == 30
    b.write(isa.MMIO_PWM_HEATER, 128)
    b.tick(10_000)


def test_plant_time_advances_with_cycles():
    p = FakePlant()
    b = Bus(plant=p)
    for _ in range(isa.CLOCK_HZ // 4):
        b.tick(4)  # 1 sim second in small steps
    assert p.dt_total == pytest.approx(1.0, abs=0.002)


def test_watchdog():
    b = Bus()
    b.write(isa.MMIO_WDOG_TIMEOUT, 4)  # 1024 cycles
    b.tick(1000)
    b.write(isa.MMIO_WDOG_KICK, 0)
    b.tick(1000)
    assert b.pending_irq() is None
    b.tick(24)
    assert b.pending_irq() == isa.VEC_WDOG
    b.ack_irq(isa.VEC_WDOG)
    b.tick(10_000)
    assert b.pending_irq() is None  # fires once until re-armed
    b.write(isa.MMIO_WDOG_KICK, 0)
    b.tick(1024)
    assert b.pending_irq() == isa.VEC_WDOG
    b.ack_irq(isa.VEC_WDOG)
    b.write(isa.MMIO_WDOG_TIMEOUT, 0)  # disabled
    b.tick(100_000)
    assert b.pending_irq() is None


def test_irq_priority_and_forced():
    b = Bus()
    b.write(isa.MMIO_TIMER_PERIOD, 10)
    b.write(isa.MMIO_TIMER_CTRL, 1)
    b.write(isa.MMIO_UART_CTRL, 1)
    b.uart_feed("x")
    b.tick(10)
    assert b.pending_irq() == isa.VEC_TIMER  # lowest vector wins
    b.ack_irq(isa.VEC_TIMER)
    assert b.pending_irq() == isa.VEC_UART
    b.read(isa.MMIO_UART_RX)
    b.raise_irq(isa.VEC_GPIO)
    assert b.pending_irq() == isa.VEC_GPIO
    b.ack_irq(isa.VEC_GPIO)
    assert b.pending_irq() is None
    assert b.irq_taken[isa.VEC_GPIO] == 1


def test_timer_rearm_and_disable():
    b = Bus()
    b.write(isa.MMIO_TIMER_PERIOD, 100)
    b.write(isa.MMIO_TIMER_CTRL, 1)
    b.tick(50)
    b.write(isa.MMIO_TIMER_PERIOD, 200)  # restarts the countdown
    b.tick(150)
    assert b.pending_irq() is None
    b.tick(50)
    assert b.pending_irq() == isa.VEC_TIMER
    b.ack_irq(isa.VEC_TIMER)
    b.write(isa.MMIO_TIMER_CTRL, 0)
    b.tick(10_000)
    assert b.pending_irq() is None
    assert b.read(isa.MMIO_TIMER_TICKS) == 1


def test_negative_address_is_masked():
    b = Bus()
    with pytest.raises(BusError):
        b.write(-1, 5)  # 0xFFFF: unmapped MMIO, not mem[-1]
    assert b.mem[-1] == 0
    b.write(-0x100 - 1, 7)  # 0xFEFF: plain RAM
    assert b.read(0xFEFF) == 7
