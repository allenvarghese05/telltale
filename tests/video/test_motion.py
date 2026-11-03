import json
import math

import numpy as np
import pytest

from telltale.config import CACHE
from telltale.core.manifest import DEFAULT_POLYGON
from telltale.video.motion import lane_change_events, lateral_offsets, time_to_lane_crossing

POLY_PX = [(x * 1280, y * 720) for x, y in DEFAULT_POLYGON]


def _dets(us, bottom=600.0, width=80.0):
    """Boxes placed so that their bottom-centre lands at lateral offset u in the lane."""
    from telltale.video.lane import _lane_edges, _x_at

    left, right = _lane_edges(POLY_PX)
    x_left, x_right = _x_at(left, bottom), _x_at(right, bottom)
    out = []
    for f, u in enumerate(us):
        cx = x_left + u * (x_right - x_left)
        out.append({"frame": f, "box": [cx - width / 2, bottom - 50, cx + width / 2, bottom]})
    return out


def test_lateral_offsets_are_measured_in_lane_widths():
    frames, u = lateral_offsets(_dets([0.5] * 40), POLY_PX)
    assert len(frames) == 40
    assert u[0] == pytest.approx(0.5, abs=1e-6)


def test_offsets_are_dropped_near_the_vanishing_point():
    """The lane edges converge; above that the lane has no width and `u` is not a measurable quantity."""
    far = [{"frame": f, "box": [600.0, 320.0, 640.0, 340.0]} for f in range(40)]
    frames, _ = lateral_offsets(far, POLY_PX)
    assert len(frames) == 0


def test_a_steady_crossing_is_one_lane_change_event():
    us = [1.4] * 20 + list(np.linspace(1.4, 0.5, 40)) + [0.5] * 20
    events = lane_change_events(_dets(us), 30.0, POLY_PX)
    assert len(events) == 1
    assert events[0].direction == "left"
    assert events[0].delta_u < -0.5
    # The fit window is centred, so the slope turns significant up to half a window before the motion's
    # midpoint reaches it: the onset is localised to within ~0.25s at 30fps, never later than the truth.
    assert 13 / 30 <= events[0].start_t <= 45 / 30


def test_a_car_holding_its_lane_produces_no_event():
    rng = np.random.default_rng(11)
    us = [0.5 + rng.normal(0, 0.02) for _ in range(90)]
    assert lane_change_events(_dets(us), 30.0, POLY_PX) == []


def test_time_to_lane_crossing_counts_down_from_outside():
    assert time_to_lane_crossing(1.15, -0.3) == pytest.approx(0.5, abs=1e-6)
    assert time_to_lane_crossing(-0.2, 0.4) == pytest.approx(0.5, abs=1e-6)


def test_time_to_lane_crossing_is_infinite_when_not_approaching():
    assert math.isinf(time_to_lane_crossing(1.15, 0.3))
    assert math.isinf(time_to_lane_crossing(0.5, -0.3))


def test_cand38_shows_two_lane_change_attempts():
    """Regression against a real track: the human watching this clip saw two attempts, ~5.5s and ~6.5s.

    The track is committed under `cache/sam/`; the clip's own entry is not, because `data/clips/` holds
    unreviewed candidates. Everything this needs is the track plus the default polygon.
    """
    tracks = json.loads((CACHE / "sam" / "cand38.json").read_text())
    poly = [(x * tracks["width"], y * tracks["height"]) for x, y in DEFAULT_POLYGON]
    dets = sorted(tracks["objects"]["3"], key=lambda d: d["frame"])
    events = lane_change_events(dets, tracks["fps"], poly)
    leftward = [e for e in events if e.direction == "left"]
    assert len(leftward) == 2
    assert all(4.0 <= e.start_t <= 8.0 for e in leftward)
