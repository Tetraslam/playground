"""Thermal plant: a ~20 L water tank with a heater, a fan, drifting ambient and a door.

Physics (plant seconds, SI units):

    C dT/dt = P_heat - UA_eff * (T - T_amb_eff)

- C = 20 kg water * 4186 J/(kg K) ~ 83.7 kJ/K
- heater: up to 3 kW, the element lags the command (first-order, tau 20 s)
- losses: UA 15 W/K, multiplied by (1 + 5 * fan); an open door adds a cold
  draft (UA * 2.5, ambient 8 degC colder)
- ambient: 20 degC + 4 degC day/night sine (40 min "day") + a slow random walk
- sensor: first-order lag (tau 4 s) + gaussian noise (0.08 degC) per read
- boiling: temperature caps at 100 degC and `boiled` latches

`time_scale` compresses physics: one sim-second (cycles / CLOCK_HZ) is
`time_scale` plant-seconds, so a 20 -> 45 degC warm-up takes ~12 sim seconds.

Determinism: door events and ambient drift are pre-scheduled from the seed and
integrated on a fixed internal grid, so the trajectory does not depend on how
the caller slices `dt`. Sensor noise uses its own RNG stream (one draw per read).
"""

from __future__ import annotations

import math
import random

WATER_C = 20.0 * 4186.0  # J/K
HEATER_W = 3000.0
UA = 15.0  # W/K, insulated tank
FAN_GAIN = 5.0  # fan=1 -> 6x losses
DOOR_UA_MULT = 2.5
DOOR_DRAFT = 8.0  # degC colder air with the door open
HEATER_TAU = 20.0  # s, element lag
SENSOR_TAU = 4.0  # s
SENSOR_NOISE = 0.08  # degC (1 sigma)
AMBIENT_MEAN = 20.0
AMBIENT_SWING = 4.0
DAY_PERIOD = 2400.0  # plant s
DOOR_MEAN_GAP = 2400.0  # plant s between openings (mean)
DOOR_MEAN_OPEN = 180.0  # plant s open (mean)
BOIL = 100.0
H = 0.25  # internal integration step, plant seconds


class Plant:
    def __init__(self, seed: int = 0, time_scale: float = 60.0):
        self.seed = seed
        self.time_scale = float(time_scale)
        self._rng = random.Random(seed * 7919 + 1)  # door + drift schedule
        self._noise = random.Random(seed * 104729 + 2)  # sensor noise
        self.heater = 0.0  # command, 0..1
        self.fan = 0.0  # command, 0..1
        self.setpoint = 45.0
        self.sensor_override: float | None = None
        self.doors_enabled = True

        self.t = 0.0  # plant seconds
        self._phase = self._rng.uniform(0, 2 * math.pi)
        self._drift = 0.0
        self.temp = self._ambient_at(0.0)
        self.sensor = self.temp
        self.element = 0.0  # actual heater output fraction (lagged)
        self.door_open = False
        self._door_manual_until: float | None = None
        self._next_door = self._rng.expovariate(1 / DOOR_MEAN_GAP)
        self._door_close = math.inf
        self.boiled = False
        self.max_temp = self.temp
        self._acc = 0.0  # pending plant seconds below one H
        self._events: list[str] = []

    # ------------------------------------------------------------ dynamics

    def _ambient_at(self, t: float) -> float:
        return (
            AMBIENT_MEAN
            + AMBIENT_SWING * math.sin(2 * math.pi * t / DAY_PERIOD + self._phase)
            + self._drift
        )

    def _door_tick(self) -> None:
        t = self.t
        if self._door_manual_until is not None:
            if t >= self._door_manual_until:
                self._door_manual_until = None
                if not (self.doors_enabled and self._door_close < math.inf):
                    self._set_door(False)
            return
        if self.door_open and t >= self._door_close:
            self._door_close = math.inf
            self._set_door(False)
        if t >= self._next_door:
            open_for = self._rng.expovariate(1 / DOOR_MEAN_OPEN)
            self._next_door = t + open_for + self._rng.expovariate(1 / DOOR_MEAN_GAP)
            if self.doors_enabled and not self.door_open:
                self._door_close = t + open_for
                self._set_door(True)

    def _set_door(self, is_open: bool) -> None:
        if is_open != self.door_open:
            self.door_open = is_open
            self._events.append("door open" if is_open else "door closed")

    def _substep(self, h: float) -> None:
        self._door_tick()
        # slow ambient random walk, mean-reverting (always consumes one draw per step)
        self._drift += -0.0005 * h * self._drift + 0.01 * math.sqrt(h) * self._rng.gauss(0, 1)
        amb = self._ambient_at(self.t)
        ua = UA * (1 + FAN_GAIN * _clamp01(self.fan))
        if self.door_open:
            ua *= DOOR_UA_MULT
            amb -= DOOR_DRAFT
        a = h / HEATER_TAU
        self.element += (_clamp01(self.heater) - self.element) * (a if a < 1 else 1)
        power = HEATER_W * self.element - ua * (self.temp - amb)
        self.temp += h * power / WATER_C
        if self.temp >= BOIL:
            self.temp = BOIL
            if not self.boiled:
                self.boiled = True
                self._events.append("boiled")
        a = h / SENSOR_TAU
        self.sensor += (self.temp - self.sensor) * (a if a < 1 else 1)
        if self.temp > self.max_temp:
            self.max_temp = self.temp
        self.t += h

    def step(self, dt: float) -> None:
        """Advance by `dt` sim seconds (cheap for tiny dt: accumulates to H)."""
        self._acc += dt * self.time_scale
        while self._acc >= H - 1e-9:  # epsilon: float sums of tiny dt land just under H
            self._acc -= H
            self._substep(H)

    # ------------------------------------------------------------ sensors

    def read_temp(self) -> float:
        if self.sensor_override is not None:
            return self.sensor_override
        return self.sensor + self._noise.gauss(0, SENSOR_NOISE)

    def ambient(self) -> float:
        a = self._ambient_at(self.t)
        return a - DOOR_DRAFT if self.door_open else a

    # ------------------------------------------------------------ disturbances

    def open_door(self, plant_seconds: float = 120.0) -> None:
        """Force the door open for a while (dash/faults hook)."""
        self._door_manual_until = self.t + plant_seconds
        self._set_door(True)

    def pop_events(self) -> list[str]:
        """Plant events since the last call: 'door open', 'door closed', 'boiled'."""
        ev, self._events = self._events, []
        return ev

    def state(self) -> dict:
        return {
            "t": self.t,
            "temp": self.temp,
            "sensor": self.sensor if self.sensor_override is None else self.sensor_override,
            "ambient": self.ambient(),
            "heater": _clamp01(self.heater),
            "fan": _clamp01(self.fan),
            "element": self.element,
            "setpoint": self.setpoint,
            "door_open": self.door_open,
            "boiled": self.boiled,
            "max_temp": self.max_temp,
        }


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def demo_pid(
    seconds: float = 300.0,
    seed: int = 0,
    kp: float = 0.25,
    ki: float = 0.01,
    kd: float = 0.0,
    dt: float = 0.1,
) -> list[dict]:
    """Host-side reference PID (float) driving the plant: a physics sanity check and
    a baseline for the firmware controller. Returns trace samples (plots.py format)."""
    p = Plant(seed=seed)
    integ, prev, trace = 0.0, None, []
    steps = int(seconds / dt)
    for k in range(steps):
        if k == steps // 3:
            p.setpoint = 60.0
        meas = p.read_temp()
        err = p.setpoint - meas
        deriv = 0.0 if prev is None else (meas - prev) / (dt * p.time_scale)
        prev = meas
        u = kp * err + ki * integ - kd * deriv
        if 0.0 < u < 1.0 or (u >= 1.0 and err < 0) or (u <= 0.0 and err > 0):
            integ += err * dt * p.time_scale  # conditional integration (anti-windup)
        p.heater = _clamp01(u)
        p.fan = 1.0 if meas > p.setpoint + 3 else 0.0
        p.step(dt)
        s = p.state()
        trace.append(
            {
                "t": (k + 1) * dt,
                "plant_t": s["t"],
                "temp": s["temp"],
                "setpoint": s["setpoint"],
                "ambient": s["ambient"],
                "heater": s["heater"],
                "fan": s["fan"],
                "task": None,
                "events": p.pop_events(),
            }
        )
    return trace


if __name__ == "__main__":
    tr = demo_pid()
    for s in tr[:: len(tr) // 15]:
        print(
            f"t={s['t']:6.1f}s  T={s['temp']:6.2f}  S={s['setpoint']:5.1f}  H={s['heater']:.2f}  F={s['fan']:.0f}  {s['events']}"
        )
    print("max temp", max(s["temp"] for s in tr))
