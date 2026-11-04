import json

import numpy as np
import pytest

from telltale.config import CACHE
from telltale.core.manifest import DEFAULT_POLYGON
from telltale.video.facts import compute_video_facts
from telltale.video.lane import collision_course_frame, lane_polygon_px
from telltale.video.ttc import ttc_series

FPS = 30.0
CLIP = {"clip_id": "syn", "time_of_event": 3.0, "ego_lane_polygon": DEFAULT_POLYGON}
TRACKS = {"fps": FPS, "width": 1280, "height": 720}
POLY = lane_polygon_px(TRACKS, CLIP)


def _dets(boxes):
    return [{"frame": f, "box": list(b)} for f, b in enumerate(boxes)]


def test_height_ttc_sees_an_approach_that_width_misses():
    """A box clipped at the frame edge stops widening; its height still grows as the vehicle closes."""
    dets = _dets([[900.0, 400.0 - 4 * f, 1280.0, 450.0 + 4 * f] for f in range(60)])
    _, by_width = ttc_series(dets, FPS)
    _, by_height = ttc_series(dets, FPS, dimension="height")
    assert np.isinf(by_width[30])
    assert np.isfinite(by_height[30])


def test_a_vehicle_closing_fast_while_touching_our_lane_is_on_a_collision_course():
    dets = _dets([[700.0, 400.0 - 4 * f, 1000.0, 450.0 + 4 * f] for f in range(60)])
    assert collision_course_frame(dets, FPS, POLY, 1280) is not None


def test_a_vehicle_alongside_whose_height_is_flat_is_not():
    """cand56's overtaking pickup: its box widens as more of it slides into view, but it is not getting closer."""
    dets = _dets([[0.0, 250.0, 400.0 + 3 * f, 555.0] for f in range(60)])
    assert collision_course_frame(dets, FPS, POLY, 1280) is None


def test_a_vehicle_closing_outside_our_lane_is_not():
    """An oncoming car in its own lane grows as it approaches, but never touches our path."""
    dets = _dets([[1150.0, 400.0 - 2 * f, 1270.0, 440.0 + 2 * f] for f in range(60)])
    assert collision_course_frame(dets, FPS, POLY, 1280) is None


@pytest.mark.parametrize(
    ("clip_id", "onset", "reason", "struck"),
    [
        ("cand36", 6.1333, "closing", "1"),
        ("cand37", 6.8301, "closing", "3"),
        ("cand38", 5.9, "closing", "3"),
        ("cand63", 2.7213, "entering", "0"),
    ],
)
def test_demo_clips_are_unchanged(clip_id, onset, reason, struck):
    """Every committed live demo run was investigated on these facts; changing them would invalidate it."""
    tracks = json.loads((CACHE / "sam" / f"{clip_id}.json").read_text())
    clip = {"clip_id": clip_id, "time_of_event": 8.0, "ego_lane_polygon": DEFAULT_POLYGON}
    video = compute_video_facts(tracks, clip)
    assert video.target_object_id == struck
    assert video.hazard_onset_reason == reason
    assert round(video.hazard_onset_t, 4) == onset


def _hazards(clip_id):
    from telltale.video.hazard import hazard_onsets

    tracks = json.loads((CACHE / "sam" / f"{clip_id}.json").read_text())
    return hazard_onsets(tracks, {"clip_id": clip_id, "time_of_event": 8.0, "ego_lane_polygon": DEFAULT_POLYGON})


def test_collision_course_places_a_vehicle_no_lane_test_can():
    """cand14: the taxi striking our right side never satisfies a lane test; collision course catches it."""
    taxi = [h for h in _hazards("cand14") if h.object_id == "4"]
    assert [(round(h.onset_t, 2), h.reason) for h in taxi] == [(5.74, "collision_course")]


def test_collision_course_never_overrides_a_lane_based_onset():
    """It is a fallback: where entering, predicted or closing fires, that reason and time stand."""
    turner = [h for h in _hazards("cand60") if h.object_id == "2"]
    assert turner[0].reason == "closing"


def test_the_turning_car_is_the_first_hazard_on_cand60():
    assert _hazards("cand60")[0].object_id == "2"
