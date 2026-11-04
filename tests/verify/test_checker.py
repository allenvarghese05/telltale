import pytest

from telltale.core.schema import Claim, Fact
from telltale.evidence.store import EvidenceStore
from telltale.verify.checker import check_all, check_claim, check_verdict


@pytest.fixture
def store():
    return EvidenceStore(
        [
            Fact("VID:hazard_onset_t", 2.0, "s", "VID", "sam"),
            Fact("AV:first_seen_t", 3.35, "s", "AV", "mcap"),
            Fact("PROFILE:perception_threshold_s", 0.3, "s", "PROFILE", "car"),
            Fact("ATTR:label", "PERCEPTION_LATE", "", "ATTR", "attr", "derived"),
            Fact("ATTR:noncausal_faults", "none", "", "ATTR", "attr", "derived"),
            Fact("CF:run1_impact_speed_mps", 2.5, "m/s", "CF", "simulate(...)", "derived"),
            Fact("WIT:other_vehicle_lane_change_t", 2.2, "s", "WIT", "spark", "observation"),
            Fact("WIT:other_vehicle_turn_signal", "no", "", "WIT", "spark", "observation"),
            Fact("WIT2:turn_signal", "no", "", "WIT2", "spark recheck", "observation"),
        ]
    )


DIFF = {"op": "diff", "a": "AV:first_seen_t", "b": "VID:hazard_onset_t", "equals": 1.35}
EV = ["AV:first_seen_t", "VID:hazard_onset_t"]


def test_verified_timing_claim_with_unit_conversion(store):
    c = Claim("Detection came 1.35 s (1350 ms) after the vehicle entered the lane.", "timing", EV, DIFF)
    assert check_claim(c, store).status == "VERIFIED"


def test_unsupported_number_is_blocked(store):
    r = check_claim(Claim("Detection lagged by 0.9 s.", "timing", EV, DIFF), store)
    assert r.status == "BLOCKED"
    assert "0.9" in r.reasons[0]


def test_false_assertion_is_blocked(store):
    assert check_claim(Claim("Detection lagged.", "timing", EV, {**DIFF, "equals": 0.5}), store).status == "BLOCKED"


def test_unknown_evidence_is_blocked(store):
    r = check_claim(Claim("The driver braked.", "timing", ["CAN:driver_brake_t"]), store)
    assert r.status == "BLOCKED"
    assert "unknown evidence" in r.reasons[0]


def test_legal_conclusion_is_blocked(store):
    r = check_claim(Claim("The other driver is at fault.", "attribution", ["VID:hazard_onset_t"]), store)
    assert r.status == "BLOCKED"
    assert "legal" in r.reasons[0]


def test_driver_state_is_blocked(store):
    r = check_claim(Claim("The driver was distracted.", "other", ["VID:hazard_onset_t"]), store)
    assert r.status == "BLOCKED"
    assert "driver-state" in r.reasons[0]


def test_single_source_observation_is_uncorroborated(store):
    r = check_claim(Claim("The other vehicle did not signal.", "observation", ["WIT:other_vehicle_turn_signal"]), store)
    assert r.status == "UNCORROBORATED"


def test_independent_recheck_corroborates(store):
    c = Claim(
        "The other vehicle did not signal.",
        "observation",
        ["WIT:other_vehicle_turn_signal", "WIT2:turn_signal"],
        {"op": "same", "a": "WIT:other_vehicle_turn_signal", "b": "WIT2:turn_signal"},
    )
    assert check_claim(c, store).status == "VERIFIED"


def test_witness_time_agrees_with_sam(store):
    c = Claim(
        "The witness saw the lane change at about 2.2 s, consistent with SAM's 2.0 s.",
        "observation",
        ["WIT:other_vehicle_lane_change_t", "VID:hazard_onset_t"],
        {"op": "agree", "a": "WIT:other_vehicle_lane_change_t", "b": "VID:hazard_onset_t", "within": 0.5},
    )
    assert check_claim(c, store).status == "VERIFIED"


def test_threshold_comparison_and_model_names_ok(store):
    c = Claim(
        "Per SAM 3.1, detection at 3.35 s vs entry at 2.0 s exceeded the 0.3 s tolerance.",
        "timing",
        ["AV:first_seen_t", "VID:hazard_onset_t", "PROFILE:perception_threshold_s"],
        DIFF,
    )
    assert check_claim(c, store).status == "VERIFIED"


def test_counterfactual_claim_kmh(store):
    c = Claim(
        "With nominal detection the impact would drop to 9 km/h.",
        "physics",
        ["CF:run1_impact_speed_mps"],
        {"op": "value", "fact": "CF:run1_impact_speed_mps", "equals": 2.5},
    )
    assert check_claim(c, store).status == "VERIFIED"


def test_assertion_must_only_use_cited_facts(store):
    assert check_claim(Claim("Lag 1.35 s.", "timing", ["AV:first_seen_t"], DIFF), store).status == "BLOCKED"


def test_verdict_verified_and_rejected(store):
    assert check_verdict("PERCEPTION_LATE", store)["status"] == "VERIFIED"
    r = check_verdict("BRAKE_ACTUATION_LATE", store)
    assert r["status"] == "REJECTED"
    assert "PERCEPTION_LATE" in r["reason"]


def test_check_all_counts(store):
    res = check_all([Claim("The driver was distracted.", "other", ["VID:hazard_onset_t"])], store)
    assert res["counts"] == {"VERIFIED": 0, "UNCORROBORATED": 0, "BLOCKED": 1}


def test_an_interval_and_its_threshold_verify_when_both_are_cited(store):
    """The shape the agent must use: `measure` results are not facts, so a diff assertion licenses the interval.

    Nine live claims were blocked for stating a correct interval without this, so it is pinned here.
    """
    claim = Claim(
        "The system took 1.35 s to notice the vehicle, above the 0.3 s it is allowed.",
        "timing",
        ["AV:first_seen_t", "VID:hazard_onset_t", "PROFILE:perception_threshold_s"],
        DIFF,
    )
    assert check_claim(claim, store).status == "VERIFIED"


def test_stating_an_interval_without_a_diff_assertion_is_blocked(store):
    """`measure` gives the agent the number, but nothing in the store holds it, so prose alone cannot cite it."""
    claim = Claim(
        "Perception took 1.35 s.",
        "timing",
        ["AV:first_seen_t", "VID:hazard_onset_t"],
        None,
    )
    assert check_claim(claim, store).status == "BLOCKED"
