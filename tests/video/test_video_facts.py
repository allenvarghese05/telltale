import math

import numpy as np
import pytest

from telltale.core.manifest import DEFAULT_POLYGON
from telltale.video.facts import compute_video_facts, danger_onset_t
from telltale.video.lane import in_lane_laterally, lane_entry_frame
from telltale.video.ttc import first_sustained_below, ttc_series


def synthetic_tracks():
    target, far = [], []
    for f in range(90):
        cx = 300.0 if f < 30 else min(640.0, 300.0 + (f - 30) * (340.0 / 15.0))
        w = 100.0 + 4.0 * f
        bottom = 500.0 + 2.0 * f
        target.append({"frame": f, "box": [cx - w / 2, bottom - 0.75 * w, cx + w / 2, bottom]})
        far.append({"frame": f, "box": [885.0, 400.0, 915.0, 420.0]})
    return {"fps": 30.0, "width": 1280, "height": 720, "objects": {"1": target, "2": far}}


CLIP = {"clip_id": "syn", "time_of_event": 2.9, "ego_lane_polygon": DEFAULT_POLYGON}


POLY_PX = [(x * 1280, y * 720) for x, y in DEFAULT_POLYGON]


def test_in_lane_laterally_uses_the_lane_edges():
    assert in_lane_laterally(640, 700, POLY_PX)
    assert not in_lane_laterally(100, 700, POLY_PX)


def test_in_lane_laterally_extrapolates_above_the_polygon():
    """The polygon's top edge is a viewing-distance cutoff, not a lane boundary."""
    above = 400.0
    assert above < min(p[1] for p in POLY_PX)
    assert in_lane_laterally(640, above, POLY_PX)
    assert not in_lane_laterally(1100, above, POLY_PX)


def test_approaching_lead_vehicle_is_not_a_lane_entry():
    """Measured on cand36: a lead car's box bottom descends past the polygon top purely by closing."""
    dets = [{"frame": f, "box": [628.0 - 20, 300.0, 628.0 + 20, 397.0 + f]} for f in range(60)]
    assert lane_entry_frame(dets, POLY_PX) is None


def test_target_lane_entry_and_ttc():
    vf = compute_video_facts(synthetic_tracks(), CLIP)
    assert vf.target_object_id == "1"
    assert 32 / 30 <= vf.lane_entry_t <= 37 / 30
    assert vf.impact_t == 2.9
    assert 1.5 < vf.ttc_at_entry < 2.5


def test_danger_onset_is_no_later_than_lane_entry():
    vf = compute_video_facts(synthetic_tracks(), CLIP)
    onset = danger_onset_t(synthetic_tracks(), CLIP)
    assert onset is not None
    assert onset <= vf.lane_entry_t + 1e-9


def test_a_target_already_in_lane_has_no_entry():
    """A lead vehicle in the lane from frame 0 never *enters* it; reporting 0.0 s would be a fabrication."""
    poly = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    dets = [{"frame": f, "box": [40.0, 40.0, 60.0, 50.0]} for f in range(20)]
    assert lane_entry_frame(dets, poly) is None


def test_lane_entry_is_found_once_the_target_crosses_in():
    poly = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    dets = [{"frame": f, "box": [140.0, 40.0, 160.0, 50.0] if f < 5 else [40.0, 40.0, 60.0, 50.0]} for f in range(20)]
    assert lane_entry_frame(dets, poly) == 5


def test_shrinking_box_has_infinite_ttc():
    dets = [{"frame": f, "box": [0, 0, 200 - f, 100]} for f in range(20)]
    _, ttc = ttc_series(dets, 30.0)
    assert math.isinf(ttc[10])


def test_single_frame_box_merge_does_not_corrupt_ttc():
    """SAM occasionally merges the target's box with a neighbour for one frame (measured on cand38)."""
    clean = [{"frame": f, "box": [0.0, 0.0, 100.0 + 4.0 * f, 100.0]} for f in range(60)]
    spiked = [dict(d, box=list(d["box"])) for d in clean]
    spiked[30]["box"][2] = 600.0
    _, ttc_clean = ttc_series(clean, 30.0)
    _, ttc_spiked = ttc_series(spiked, 30.0)
    assert ttc_spiked[30] == pytest.approx(ttc_clean[30], abs=0.1)


def test_jitter_on_a_small_box_does_not_trigger_danger_onset():
    """A 20px box jittering by its own width must not imply an imminent collision."""
    rng = np.random.default_rng(7)
    dets = [{"frame": f, "box": [0.0, 0.0, 20.0 + rng.normal(0, 9.0), 40.0]} for f in range(90)]
    frames, ttc = ttc_series(dets, 30.0)
    assert first_sustained_below(frames, ttc, 2.0) is None
