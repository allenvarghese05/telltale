import json

import numpy as np

from telltale.config import CACHE
from telltale.core.manifest import DEFAULT_POLYGON
from telltale.video.hazard import hazard_onsets

POLY = DEFAULT_POLYGON
FPS = 30.0


def _box_at(u, bottom, width, poly_px):
    from telltale.video.lane import _lane_edges, _x_at

    left, right = _lane_edges(poly_px)
    x_left, x_right = _x_at(left, bottom), _x_at(right, bottom)
    cx = x_left + u * (x_right - x_left)
    return [cx - width / 2, bottom - 0.75 * width, cx + width / 2, bottom]


def _tracks(objects):
    return {"fps": FPS, "width": 1280, "height": 720, "objects": objects}


POLY_PX = [(x * 1280, y * 720) for x, y in POLY]
CLIP = {"clip_id": "syn", "time_of_event": 3.0, "ego_lane_polygon": POLY}


def _closing_lead(n=90, u=0.5):
    """A car in our lane, growing in the frame: a developing rear-end."""
    return [{"frame": f, "box": _box_at(u, 560.0 + 1.6 * f, 70.0 + 3.0 * f, POLY_PX)} for f in range(n)]


def _parallel_neighbour(n=90):
    """A car one lane over, same speed: never a hazard."""
    return [{"frame": f, "box": _box_at(1.6, 600.0, 90.0, POLY_PX)} for f in range(n)]


def test_a_parallel_neighbour_is_not_a_hazard():
    onsets = hazard_onsets(_tracks({"9": _parallel_neighbour()}), CLIP)
    assert onsets == []


def test_a_closing_lead_vehicle_is_a_hazard_without_any_lane_change():
    onsets = hazard_onsets(_tracks({"1": _closing_lead()}), CLIP)
    assert len(onsets) == 1
    assert onsets[0].object_id == "1"
    assert onsets[0].reason == "closing"


def test_the_earliest_hazard_across_objects_wins():
    onsets = hazard_onsets(_tracks({"1": _closing_lead(), "9": _parallel_neighbour()}), CLIP)
    assert [o.object_id for o in onsets] == ["1"]


def test_cand38_hazards_are_found_on_a_real_track():
    """Real track: object 3 moves into our lane while object 5 leaves it. Both deserve assessment."""
    clip = {"clip_id": "cand38", "time_of_event": 8.0, "ego_lane_polygon": POLY}
    tracks = json.loads((CACHE / "sam" / "cand38.json").read_text())
    onsets = hazard_onsets(tracks, clip)
    assert onsets, "expected at least one hazard on a real collision clip"
    assert all(0.0 <= o.onset_t <= clip["time_of_event"] for o in onsets)
    assert onsets == sorted(onsets, key=lambda o: o.onset_t)
    assert not any(np.isnan(o.onset_t) for o in onsets)
