import json

from telltale.config import CACHE
from telltale.core.manifest import DEFAULT_POLYGON
from telltale.video.scene import scene_facts, summarize_scene

CLIP = {"clip_id": "cand38", "time_of_event": 8.0, "ego_lane_polygon": DEFAULT_POLYGON}


def _tracks():
    return json.loads((CACHE / "sam" / "cand38.json").read_text())


def test_summary_counts_vehicles_and_hazards():
    scene = summarize_scene(_tracks(), CLIP)
    assert scene.tracked_vehicles == 16
    assert scene.hazards
    assert scene.first_hazard_t == scene.hazards[0].onset_t


def test_danger_onset_follows_the_struck_vehicle_not_the_earliest_hazard():
    """Perception latency is about the threat that was hit, not whichever car looked dangerous first."""
    scene = summarize_scene(_tracks(), CLIP)
    of_target = [h for h in scene.hazards if h.object_id == scene.target_object_id]
    assert of_target, "the struck vehicle should itself register as a hazard"
    assert scene.danger_onset_t == of_target[0].onset_t
    assert scene.first_hazard_t < scene.danger_onset_t


def test_summary_carries_witness_conditions_through_untouched():
    scene = summarize_scene(_tracks(), CLIP, {"weather": "overcast", "lighting": "daylight"})
    assert scene.conditions == {"weather": "overcast", "lighting": "daylight"}


def test_facts_are_all_recomputable_video_facts():
    facts = scene_facts(summarize_scene(_tracks(), CLIP))
    assert {f.id for f in facts} == {"VID:hazard_vehicle_count", "VID:target_lane_changes"}
    assert all(f.source == "VID" for f in facts)
    assert all(f.derivation for f in facts)


def test_no_facts_when_nothing_was_tracked():
    empty = {"fps": 30.0, "width": 1280, "height": 720, "objects": {}}
    scene = summarize_scene(empty, CLIP)
    assert scene.danger_onset_t is None
    assert {f.id for f in scene_facts(scene)} == {"VID:hazard_vehicle_count", "VID:target_lane_changes"}
