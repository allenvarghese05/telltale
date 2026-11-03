import pytest

from telltale.physics.profiles import CAR, PROFILES, TRUCK
from telltale.physics.sim import BrakeModel, pressure_reached_time, simulate


def test_no_braking_contact_time_is_gap_over_closing_speed():
    r = simulate(25.0, 15.0, 10.0, t_request=99.0, brake=BrakeModel(8.0, 0.15), t_end=3.0)
    assert r.contact
    assert r.contact_t == pytest.approx(1.0, abs=0.005)
    assert r.impact_rel_speed == pytest.approx(10.0, abs=0.05)


def test_early_hard_braking_avoids_contact():
    r = simulate(20.0, 15.0, 10.0, t_request=0.0, brake=BrakeModel(8.0, 0.15), t_end=5.0)
    assert not r.contact
    assert r.min_gap > 0


def test_pressure_reached_time_first_order():
    assert pressure_reached_time(1.0, 0.15) == pytest.approx(1.1374, abs=1e-3)


def test_nominal_actuation_is_within_profile_threshold():
    for p in (CAR, TRUCK):
        lat = pressure_reached_time(0.0, p.tau_nominal)
        assert lat < p.thresholds["actuation_s"]
    assert set(PROFILES) == {"car", "truck"}
