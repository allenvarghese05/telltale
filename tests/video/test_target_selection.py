import json

import pytest

from telltale.config import CACHE
from telltale.core.manifest import DEFAULT_POLYGON
from telltale.video.lane import select_target

FPS = 30.0
IMPACT_FRAME = 240
CLIP = {"clip_id": "syn", "time_of_event": IMPACT_FRAME / FPS, "ego_lane_polygon": DEFAULT_POLYGON}


def _tracks(objects: dict[str, list[float]]) -> dict:
    """Each object holds one fixed box for the whole second before impact."""
    frames = range(IMPACT_FRAME - 35, IMPACT_FRAME + 1)
    return {
        "fps": FPS,
        "width": 1280,
        "height": 720,
        "objects": {oid: [{"frame": f, "box": list(box)} for f in frames] for oid, box in objects.items()},
    }


PASSING_ALONGSIDE = [0.0, 300.0, 300.0, 700.0]  # big and close to the camera, but mostly left of our lane
LEAD_IN_OUR_LANE = [580.0, 560.0, 700.0, 640.0]  # smaller, squarely in our lane


def test_a_vehicle_passing_alongside_is_not_the_struck_vehicle():
    """Largest-box-at-impact picked an overtaking pickup on cand56; the struck vehicle was in our path."""
    tracks = _tracks({"pickup": PASSING_ALONGSIDE, "lead": LEAD_IN_OUR_LANE})
    assert select_target(tracks, CLIP) == "lead"


def test_falls_back_to_the_largest_box_when_nothing_was_in_our_lane():
    tracks = _tracks({"crossing": PASSING_ALONGSIDE, "small": [0.0, 650.0, 40.0, 690.0]})
    assert select_target(tracks, CLIP) == "crossing"


def test_a_vehicle_too_small_to_measure_cannot_be_the_struck_vehicle():
    """A few pixels wide in our lane is a distant car, not the one we hit."""
    tracks = _tracks({"pickup": PASSING_ALONGSIDE, "speck": [632.0, 600.0, 648.0, 612.0]})
    assert select_target(tracks, CLIP) == "pickup"


def test_raises_when_nothing_is_visible_near_impact():
    empty = {"fps": FPS, "width": 1280, "height": 720, "objects": {}}
    with pytest.raises(ValueError, match="no tracked object visible near the impact frame"):
        select_target(empty, CLIP)


@pytest.mark.parametrize(
    ("clip_id", "struck"),
    [
        ("cand56", "3"),  # the silver lead car, not the overtaking pickup (object 4)
        ("cand36", "1"),
        ("cand37", "3"),
        ("cand38", "3"),
        ("cand63", "0"),
    ],
)
def test_real_clips_pick_the_vehicle_in_our_path(clip_id, struck):
    tracks = json.loads((CACHE / "sam" / f"{clip_id}.json").read_text())
    clip = {"clip_id": clip_id, "time_of_event": 8.0, "ego_lane_polygon": DEFAULT_POLYGON}
    assert select_target(tracks, clip) == struck
