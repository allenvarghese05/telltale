from telltale.physics.attribution import Measured, attribute
from telltale.physics.counterfactual import counterfactual
from telltale.physics.profiles import CAR


def m(**kw):
    base = {
        "perception_latency": 0.2,
        "command_latency": 0.05,
        "actuation_latency": 0.14,
        "handoff_margin": None,
        "cf_nominal_contact": False,
        "data_complete": True,
    }
    base.update(kw)
    return Measured(**base)


def test_unavoidable_when_nominal_counterfactual_still_collides():
    v = attribute(m(perception_latency=1.3, cf_nominal_contact=True), CAR)
    assert v.label == "UNAVOIDABLE"
    assert v.noncausal_faults == ["perception"]


def test_largest_excess_wins():
    assert attribute(m(perception_latency=1.35), CAR).label == "PERCEPTION_LATE"
    assert attribute(m(actuation_latency=0.6), CAR).label == "BRAKE_ACTUATION_LATE"
    assert attribute(m(command_latency=0.5), CAR).label == "COMMAND_LATE"
    assert attribute(m(command_latency=None, handoff_margin=0.8), CAR).label == "LATE_HANDOFF"


def test_incomplete_data_is_inconclusive():
    assert attribute(m(perception_latency=1.35, data_complete=False), CAR).label == "INCONCLUSIVE"


def test_no_fault_found():
    assert attribute(m(), CAR).label == "NO_FAULT_FOUND"


def test_counterfactual_uses_nominal_latencies():
    r = counterfactual(25.0, 15.0, 30.0, CAR)
    assert not r.contact
    r2 = counterfactual(25.0, 15.0, 30.0, CAR, perception_s=2.9)
    assert r2.contact
