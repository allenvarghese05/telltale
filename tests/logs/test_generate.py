import json

import numpy as np
import pytest

from telltale.logs.generate import EXPECTED, ClipTiming, generate_case, sample_truth
from telltale.physics.profiles import CAR, TRUCK

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
