import pytest

import telltale.pipeline.analyze as an
from telltale.core.manifest import DEFAULT_POLYGON
from telltale.logs.generate import ClipTiming, generate_case
from telltale.physics.profiles import CAR
from telltale.pipeline.perception_sensitivity import (
    StudyCase,
    flip_margins,
    label_at,
    missed_onset_label,
    skewed,
    stability,
)
from telltale.video.facts import compute_video_facts
from tests.video.test_video_facts import synthetic_tracks

CLIP = {"clip_id": "syn", "time_of_event": 2.9, "ego_lane_polygon": DEFAULT_POLYGON}


@pytest.fixture
def case(tmp_path):
    """A brake-slow case on the synthetic clip."""
    video = compute_video_facts(synthetic_tracks(), CLIP)
    timing = ClipTiming("syn", video.hazard_onset_t, video.impact_t)
    case_id = generate_case(timing, CAR, "brake_slow", 7, tmp_path / "cases", tmp_path / "gt")
    return StudyCase(case_id, tmp_path / "cases" / case_id, video, CAR, "brake_slow", "BRAKE_ACTUATION_LATE")


def test_no_shift_reproduces_the_stored_attribution(case):
    assert label_at(case, 0.0) == "BRAKE_ACTUATION_LATE"


def test_a_shift_past_impact_or_before_the_clip_has_no_verdict(case):
    assert label_at(case, case.video.impact_t - case.video.hazard_onset_t) is None
    assert label_at(case, -case.video.hazard_onset_t - 0.5) is None


def test_flip_margins_are_none_or_positive(case):
    margins = flip_margins(case, step=0.25, span=1.0)
    assert set(margins) == {"early", "late"}
    assert all(m is None or m > 0 for m in margins.values())


def test_missed_onset_drops_only_the_perception_layer(case):
    assert missed_onset_label(case) == "BRAKE_ACTUATION_LATE"


def test_adas_skew_inside_the_search_window_is_absorbed(case, tmp_path):
    result = skewed(case, tmp_path / "work", adas_s=0.5)
    assert result["label"] == "BRAKE_ACTUATION_LATE"
    assert result["av_offset_error_s"] == pytest.approx(0.0, abs=0.01)


def test_stability_counts_feasible_stable_and_correct(case):
    s = stability([case], errors=[0.0, 0.0, 1e6])
    assert s == {"cases": 1, "draws": 3, "feasible": 2, "stable": 2, "correct": 2, "infeasible": 1, "flips": {}}


def test_ground_truth_is_never_read_by_the_checker_paths():
    """Only this study's scoring compares with the expected label; the analyze path never sees it."""
    assert "expected" not in an.CaseEvidence.__dataclass_fields__
