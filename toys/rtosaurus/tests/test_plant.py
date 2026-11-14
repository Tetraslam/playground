import math

import pytest
from rtosaurus import plots
from rtosaurus.plant import Plant, demo_pid


def run(p: Plant, sim_s: float, dt: float = 0.01) -> None:
    for _ in range(int(sim_s / dt)):
        p.step(dt)


def test_deterministic_per_seed_and_independent_of_dt_slicing():
    a, b = Plant(seed=4), Plant(seed=4)
    a.heater = b.heater = 0.6
    run(a, 30, dt=0.001)
    run(b, 30, dt=0.1)
    assert a.t == pytest.approx(b.t)
    assert a.temp == pytest.approx(b.temp)
    assert a.door_open == b.door_open
    assert Plant(seed=5).temp != Plant(seed=4).temp


def test_full_heater_warms_and_off_cools_toward_ambient():
    p = Plant(seed=0)
    p.doors_enabled = False
    t0 = p.temp
    p.heater = 1.0
    run(p, 10)
    assert p.temp > t0 + 15  # ~2 degC per sim second at full power
    hot = p.temp
    p.heater = 0.0
    run(p, 20)
    assert p.temp < hot
    assert p.temp > p.ambient()


def test_fan_cools_faster():
    def cool(fan):
        p = Plant(seed=1)
        p.doors_enabled = False
        p.heater = 1.0
        run(p, 15)
        p.heater, p.fan = 0.0, fan
        start = p.temp
        run(p, 10)
        return start - p.temp

    assert cool(1.0) > 3 * cool(0.0)


def test_boils_and_latches_at_100():
    p = Plant(seed=2)
    p.heater = 1.0
    run(p, 120)
    assert p.boiled
    assert p.temp == 100.0
    assert "boiled" in p.pop_events()
    assert p.pop_events() == []


def test_sensor_override_and_noise():
    p = Plant(seed=3)
    reads = [p.read_temp() for _ in range(200)]
    assert 0.03 < (max(reads) - min(reads)) < 1.5
    p.sensor_override = 12.5
    assert p.read_temp() == 12.5
    assert p.state()["sensor"] == 12.5
    p.sensor_override = None
    assert abs(p.read_temp() - p.temp) < 1


def test_door_opens_eventually_and_manual_door():
    p = Plant(seed=0)
    seen = []
    for _ in range(3000):  # 300 sim s = 5 plant hours
        p.step(0.1)
        seen += p.pop_events()
    assert "door open" in seen and "door closed" in seen
    q = Plant(seed=0)
    q.doors_enabled = False
    amb = q.ambient()
    q.open_door(60)
    assert q.door_open and q.ambient() < amb - 5
    run(q, 2)
    assert not q.door_open


def test_state_keys():
    s = Plant().state()
    for k in ("t", "temp", "ambient", "heater", "fan", "setpoint", "door_open", "boiled"):
        assert k in s
    assert not math.isnan(s["temp"])


def test_reference_pid_tracks_setpoint():
    tr = demo_pid(seconds=200, seed=0)
    tail = tr[len(tr) // 2 :]
    assert max(abs(s["temp"] - s["setpoint"]) for s in tail[100:]) < 3.0
    assert max(s["temp"] for s in tr) < 70


def test_plots_write_pngs(tmp_path):
    tr = demo_pid(seconds=40, seed=1)
    for i, s in enumerate(tr):
        s["task"] = [0, 1, 8, None][i % 4]
        s["door_open"] = 100 < i < 150
    tr[50]["events"].append("fault t1")
    tr[60]["events"].append("wdog")
    plots.plot_run(tr, str(tmp_path / "run.png"), title="t")
    plots.plot_gantt(tr, str(tmp_path / "gantt.png"), names={0: "ctl", 1: "log"})
    res = [
        {
            "kind": k,
            "rate": r,
            "seed": s,
            "survived": s % (r + 1) == 0,
            "boiled": False,
            "max_temp": 50.0,
        }
        for k in ("ram-flip", "stuck-sensor")
        for r in (0, 1, 2)
        for s in range(4)
    ]
    plots.plot_campaign(res, str(tmp_path / "camp.png"))
    for f in ("run.png", "gantt.png", "camp.png"):
        assert (tmp_path / f).stat().st_size > 5000


def test_wilson():
    p, lo, hi = plots.wilson(5, 10)
    assert p == 0.5 and lo < 0.5 < hi
    assert plots.wilson(0, 10)[1] == 0.0
