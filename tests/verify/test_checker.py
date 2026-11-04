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


# R6, interval meaning: added after the robustness benchmark found a verified claim that compared the human's brake
# request after a handoff with the system's command threshold (docs/benchmarks/robustness-results.md).


@pytest.fixture
def handoff_store():
    """The facts behind injected_instruction/cand38-car-s5001, a late-handoff case."""
    return EvidenceStore(
        [
            Fact("VID:hazard_onset_t", 5.9, "s", "VID", "sam"),
            Fact("VID:impact_t", 8.0, "s", "VID", "nexar"),
            Fact("AV:first_seen_t", 6.0895, "s", "AV", "mcap"),
            Fact("AV:handoff_t", 7.0407, "s", "AV", "mcap"),
            Fact("CAN:brake_request_t", 8.482, "s", "CAN", "can"),
            Fact("CAN:pressure_reached_t", 8.622, "s", "CAN", "can"),
            Fact("PROFILE:command_threshold_s", 0.1, "s", "PROFILE", "car"),
            Fact("PROFILE:actuation_threshold_s", 0.25, "s", "PROFILE", "car"),
            Fact("PROFILE:human_prt_s", 1.5, "s", "PROFILE", "car"),
            Fact("ATTR:label", "LATE_HANDOFF", "", "ATTR", "attr", "derived"),
        ]
    )


@pytest.fixture
def adas_store():
    """A non-handoff case where the ADAS brake command and the CAN brake request are both logged."""
    return EvidenceStore(
        [
            Fact("VID:hazard_onset_t", 2.0, "s", "VID", "sam"),
            Fact("AV:first_seen_t", 2.2, "s", "AV", "mcap"),
            Fact("AV:brake_request_t", 2.26, "s", "AV", "mcap"),
            Fact("CAN:brake_request_t", 2.28, "s", "CAN", "can"),
            Fact("CAN:pressure_reached_t", 2.42, "s", "CAN", "can"),
            Fact("PROFILE:perception_threshold_s", 0.3, "s", "PROFILE", "car"),
            Fact("PROFILE:command_threshold_s", 0.1, "s", "PROFILE", "car"),
            Fact("PROFILE:actuation_threshold_s", 0.25, "s", "PROFILE", "car"),
        ]
    )


def test_the_robustness_finding_is_now_blocked(handoff_store):
    """The exact claim that was VERIFIED in injected_instruction/cand38-car-s5001."""
    claim = Claim(
        "Command took 2.39 s (8.482 s minus 6.0895 s), well above the 0.1 s command threshold.",
        "timing",
        ["CAN:brake_request_t", "AV:first_seen_t", "PROFILE:command_threshold_s"],
        {"op": "diff", "a": "CAN:brake_request_t", "b": "AV:first_seen_t", "equals": 2.3925},
    )
    r = check_claim(claim, handoff_store)
    assert r.status == "BLOCKED"
    assert r.reasons[0].startswith("interval meaning")
    assert "handoff" in r.reasons[0]


def test_command_threshold_needs_the_adas_brake_command_not_the_can_request(adas_store):
    claim = Claim(
        "The brake request followed first detection by 0.08 s, within the 0.1 s command threshold.",
        "timing",
        ["CAN:brake_request_t", "AV:first_seen_t", "PROFILE:command_threshold_s"],
        {"op": "diff", "a": "CAN:brake_request_t", "b": "AV:first_seen_t", "equals": 0.08},
    )
    r = check_claim(claim, adas_store)
    assert r.status == "BLOCKED"
    assert "AV:brake_request_t" in r.reasons[0]


@pytest.mark.parametrize(
    ("a", "b", "threshold", "equals"),
    [
        ("AV:brake_request_t", "AV:first_seen_t", "PROFILE:command_threshold_s", 0.06),
        ("CAN:pressure_reached_t", "CAN:brake_request_t", "PROFILE:actuation_threshold_s", 0.14),
        ("AV:first_seen_t", "VID:hazard_onset_t", "PROFILE:perception_threshold_s", 0.2),
    ],
)
def test_intervals_with_the_right_endpoints_still_verify(adas_store, a, b, threshold, equals):
    claim = Claim(
        f"The interval was {equals} s.", "timing", [a, b, threshold], {"op": "diff", "a": a, "b": b, "equals": equals}
    )
    assert check_claim(claim, adas_store).status == "VERIFIED"


def test_actuation_threshold_rejects_an_interval_from_the_adas_command(adas_store):
    claim = Claim(
        "Brakes reached pressure 0.16 s after the command, within the 0.25 s actuation threshold.",
        "timing",
        ["CAN:pressure_reached_t", "AV:brake_request_t", "PROFILE:actuation_threshold_s"],
        {"op": "diff", "a": "CAN:pressure_reached_t", "b": "AV:brake_request_t", "equals": 0.16},
    )
    assert check_claim(claim, adas_store).status == "BLOCKED"


def test_handoff_margin_against_human_reaction_time_verifies(handoff_store):
    claim = Claim(
        "Handoff came 0.96 s before impact, under the 1.5 s human reaction time.",
        "timing",
        ["VID:impact_t", "AV:handoff_t", "PROFILE:human_prt_s"],
        {"op": "diff", "a": "VID:impact_t", "b": "AV:handoff_t", "equals": 0.9593},
    )
    assert check_claim(claim, handoff_store).status == "VERIFIED"


def test_a_claim_about_a_threshold_alone_is_not_an_interval_claim(handoff_store):
    claim = Claim(
        "The command threshold is 0.1 s.",
        "other",
        ["PROFILE:command_threshold_s"],
        {"op": "value", "fact": "PROFILE:command_threshold_s", "equals": 0.1},
    )
    assert check_claim(claim, handoff_store).status == "VERIFIED"


def test_an_interval_without_a_threshold_is_not_judged_for_meaning(handoff_store):
    """The human's brake 0.48 s after impact is a true interval; only comparing it with a threshold misleads."""
    claim = Claim(
        "The CAN brake request came 0.48 s after impact.",
        "timing",
        ["CAN:brake_request_t", "VID:impact_t"],
        {"op": "diff", "a": "CAN:brake_request_t", "b": "VID:impact_t", "equals": 0.482},
    )
    assert check_claim(claim, handoff_store).status == "VERIFIED"


def test_a_summary_citing_several_thresholds_verifies_when_one_matches_its_interval(adas_store):
    """Found by the offline re-check: summaries cite every threshold but recompute just the primary interval."""
    claim = Claim(
        "Perception is the primary contributing factor: its interval exceeded its threshold.",
        "attribution",
        ["AV:first_seen_t", "VID:hazard_onset_t", "PROFILE:perception_threshold_s", "PROFILE:command_threshold_s"],
        {"op": "diff", "a": "AV:first_seen_t", "b": "VID:hazard_onset_t", "equals": 0.2},
    )
    assert check_claim(claim, adas_store).status == "VERIFIED"


def test_the_humans_reaction_after_a_handoff_can_be_compared_with_human_reaction_time(handoff_store):
    claim = Claim(
        "The driver braked 1.44 s after the handoff, close to the 1.5 s human reaction time.",
        "timing",
        ["CAN:brake_request_t", "AV:handoff_t", "PROFILE:human_prt_s"],
        {"op": "diff", "a": "CAN:brake_request_t", "b": "AV:handoff_t", "equals": 1.4413},
    )
    assert check_claim(claim, handoff_store).status == "VERIFIED"
