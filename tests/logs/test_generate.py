import json

import numpy as np
import pytest

from telltale.logs.generate import (
    CONFUSABLE_EXPECTED,
    EXPECTED,
    HARD_EXPECTED,
    ClipTiming,
    GenerationError,
    generate_case,
    sample_truth,
)
from telltale.physics.profiles import CAR, TRUCK
from telltale.physics.sim import pressure_reached_time

TIMING = ClipTiming(clip_id="syn", hazard_onset_t=4.0, impact_t=6.2)


@pytest.mark.parametrize("profile", [CAR, TRUCK])
@pytest.mark.parametrize("story", list(EXPECTED))
def test_truth_matches_requested_story_and_hits_video_impact(profile, story):
    t = sample_truth(TIMING, profile, story, np.random.default_rng(7))
    assert t.label == EXPECTED[story]
    assert abs(t.contact_t - (TIMING.impact_t - TIMING.hazard_onset_t)) < 0.03


def test_case_files_hide_the_story(tmp_path):
    cid = generate_case(TIMING, CAR, "brake_slow", seed=3, out_root=tmp_path / "cases", gt_root=tmp_path / "gt")
    case = json.loads((tmp_path / "cases" / cid / "case.json").read_text())
    assert set(case) == {"case_id", "clip_id", "profile"}
    assert (tmp_path / "cases" / cid / "vehicle.can.log").exists()
    assert (tmp_path / "cases" / cid / "adas.mcap").exists()
    assert json.loads((tmp_path / "gt" / f"{cid}.json").read_text())["story"] == "brake_slow"


def _excess(t, profile, timing=TIMING):
    """Each layer's latency minus its tolerance, read from the hidden truth."""
    thr = profile.thresholds
    T = timing.impact_t - timing.hazard_onset_t
    out = {
        "perception": t.first_seen - thr["perception_s"],
        "actuation": pressure_reached_time(t.brake_request, t.tau) - t.brake_request - thr["actuation_s"],
    }
    if t.handoff is None:
        out["command"] = t.brake_request - t.first_seen - thr["command_s"]
    else:
        out["handoff"] = thr["human_prt_s"] - (T - t.handoff)
    return out


# A car braking at 8 m/s^2 avoids a 2 s cut-in whenever braking was meaningfully late, so "unavoidable despite a
# fault" only exists on short hazard windows.
SHORT = ClipTiming(clip_id="short", hazard_onset_t=6.8, impact_t=8.0)


def _timing(story):
    return SHORT if story == "unavoidable_with_fault" else TIMING


@pytest.mark.parametrize("profile", [CAR, TRUCK])
@pytest.mark.parametrize("story", list(HARD_EXPECTED))
def test_hard_truth_reaches_its_label_and_hits_video_impact(profile, story):
    timing = _timing(story)
    t = sample_truth(timing, profile, story, np.random.default_rng(7))
    assert t.label == HARD_EXPECTED[story]
    assert abs(t.contact_t - (timing.impact_t - timing.hazard_onset_t)) < 0.03


def test_car_cannot_be_unavoidable_with_a_fault_on_a_long_hazard_window():
    with pytest.raises(GenerationError, match="unavoidable_with_fault"):
        sample_truth(TIMING, CAR, "unavoidable_with_fault", np.random.default_rng(7))


@pytest.mark.parametrize("profile", [CAR, TRUCK])
@pytest.mark.parametrize("story", [s for s in HARD_EXPECTED if s.startswith("tight_")])
def test_tight_stories_have_two_faults_and_a_small_winning_margin(profile, story):
    for seed in range(5):
        ex = sorted(_excess(sample_truth(TIMING, profile, story, np.random.default_rng(seed)), profile).values())
        assert ex[-2] > 0
        assert 0.0 < ex[-1] - ex[-2] < 0.1


@pytest.mark.parametrize("profile", [CAR, TRUCK])
@pytest.mark.parametrize("story", [s for s in HARD_EXPECTED if s.startswith("marginal_")])
def test_marginal_stories_sit_just_over_one_limit_next_to_a_near_miss(profile, story):
    for seed in range(5):
        ex = sorted(_excess(sample_truth(TIMING, profile, story, np.random.default_rng(seed)), profile).values())
        assert 0.0 < ex[-1] <= 0.10
        assert -0.05 <= ex[-2] < 0.0


@pytest.mark.parametrize("profile", [CAR, TRUCK])
def test_unavoidable_with_fault_keeps_a_noncausal_overrun(profile):
    for seed in range(5):
        t = sample_truth(SHORT, profile, "unavoidable_with_fault", np.random.default_rng(seed))
        assert t.label == "UNAVOIDABLE"
        assert max(_excess(t, profile, SHORT).values()) > 0


def test_hard_cases_use_larger_clock_skews_the_aligner_can_still_resolve():
    truths = [sample_truth(TIMING, CAR, "marginal_perception", np.random.default_rng(s)) for s in range(20)]
    assert max(abs(t.can_skew) for t in truths) > 2.0
    assert all(abs(t.av_skew - t.can_skew) <= 1.3 for t in truths)


def test_ground_truth_label_is_the_attribution_label(tmp_path):
    cid = generate_case(TIMING, TRUCK, "tight_command_perception", 4, tmp_path / "cases", tmp_path / "gt")
    gt = json.loads((tmp_path / "gt" / f"{cid}.json").read_text())
    assert gt["expected_label"] == gt["label"] == "COMMAND_LATE"


@pytest.mark.parametrize("profile", [CAR, TRUCK])
@pytest.mark.parametrize("story", list(CONFUSABLE_EXPECTED))
def test_confusable_truth_reaches_its_label_and_hits_video_impact(profile, story):
    t = sample_truth(TIMING, profile, story, np.random.default_rng(5))
    assert t.label == CONFUSABLE_EXPECTED[story]
    assert abs(t.contact_t - (TIMING.impact_t - TIMING.hazard_onset_t)) < 0.03


def test_quick_driver_brakes_before_impact_after_a_late_handoff():
    T = TIMING.impact_t - TIMING.hazard_onset_t
    for seed in range(5):
        t = sample_truth(TIMING, CAR, "handoff_quick_driver", np.random.default_rng(seed))
        assert t.handoff < t.brake_request < T
        assert T - t.handoff < CAR.thresholds["human_prt_s"]


def test_slow_driver_after_a_timely_handoff_looks_like_a_long_command_delay():
    for seed in range(5):
        t = sample_truth(TIMING, CAR, "handoff_in_time_slow_driver", np.random.default_rng(seed))
        assert TIMING.impact_t - TIMING.hazard_onset_t - t.handoff >= CAR.thresholds["human_prt_s"]
        assert t.brake_request - t.first_seen > 1.0


def test_confusable_stories_choose_which_adas_events_are_logged():
    events = {s: sample_truth(TIMING, CAR, s, np.random.default_rng(5)).adas_events for s in CONFUSABLE_EXPECTED}
    assert events == {
        "handoff_quick_driver": "auto",
        "handoff_in_time_slow_driver": "auto",
        "adas_brake_then_handoff": "both",
        "adas_events_lost_perception": "none",
        "adas_events_lost_actuation": "none",
    }
