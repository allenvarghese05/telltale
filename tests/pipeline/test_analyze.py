import json

import pytest

import telltale.pipeline.analyze as an
from telltale.core.manifest import DEFAULT_POLYGON
from telltale.logs.generate import ClipTiming, generate_case
from telltale.physics.profiles import CAR
from telltale.video.facts import compute_video_facts
from tests.video.test_video_facts import synthetic_tracks

CLIP = {
    "clip_id": "syn",
    "file": "syn.mp4",
    "fps": 30.0,
    "width": 1280,
    "height": 720,
    "time_of_event": 2.9,
    "time_of_alert": None,
    "ego_lane_polygon": DEFAULT_POLYGON,
}
CLAIMS = [
    {"text": "The brake request was logged on CAN.", "type": "timing", "evidence": ["CAN:brake_request_t"]},
    {"text": "The driver was distracted.", "type": "other", "evidence": ["VID:hazard_onset_t"]},
]


@pytest.fixture
def case(tmp_path, monkeypatch):
    """A brake_slow case on the synthetic clip, with the pipeline's paths pointed at tmp_path."""
    cache, cases = tmp_path / "cache", tmp_path / "cases"
    (cache / "sam").mkdir(parents=True)
    (cache / "sam" / "syn.json").write_text(json.dumps(synthetic_tracks()))
    vf = compute_video_facts(synthetic_tracks(), CLIP)
    timing = ClipTiming("syn", vf.hazard_onset_t, vf.impact_t)
    case_id = generate_case(timing, CAR, "brake_slow", 7, cases, tmp_path / "gt")
    for name, value in (("CACHE", cache), ("CASES", cases), ("CLIPS", tmp_path)):
        monkeypatch.setattr(an, name, value)
    monkeypatch.setattr(an, "get_clip", lambda _clip_id: CLIP)
    return case_id, cache


def _cache_agent_run(cache, case_id, verdict):
    (cache / "agent").mkdir(exist_ok=True)
    run = {"model": "fake", "digest": "x", "verdict": verdict, "tool_calls": [], "agent_facts": [], "claims": CLAIMS}
    (cache / "agent" / f"{case_id}.json").write_text(json.dumps(run))


def test_store_carries_curated_scene_facts(case):
    case_id, _ = case
    store = an.build_case_store(an.CASES / case_id).store
    assert store.has("VID:hazard_onset_t")
    assert store.has("VID:hazard_vehicle_count")
    assert store.has("VID:target_lane_changes")


def test_counterfactual_tool_uses_the_stores_physics_inputs(case):
    case_id, _ = case
    case_evidence = an.build_case_store(an.CASES / case_id)
    profile = case_evidence.profile
    run = an.counterfactual_fn(case_evidence.store, profile)
    nominal = profile.nominal
    assert run(nominal["perception_s"], nominal["command_s"], profile.tau_nominal)["contact"] is False
    assert run(2.5, nominal["command_s"], profile.tau_nominal)["contact"] is True


def test_analyze_verifies_a_correct_agent_verdict(case):
    case_id, cache = case
    _cache_agent_run(cache, case_id, "BRAKE_ACTUATION_LATE")
    bundle = an.analyze(case_id)
    assert bundle["verdict"]["status"] == "VERIFIED"
    assert bundle["verdict"]["independent_label"] == "BRAKE_ACTUATION_LATE"
    assert bundle["counts"] == {"VERIFIED": 1, "UNCORROBORATED": 0, "BLOCKED": 1}
    assert bundle["events"][0]["key"] == "VID:hazard_onset_t"
    assert all("thumb" in e for e in bundle["events"])
    assert bundle["counterfactual_inputs"]["d0"] > 0
    assert bundle["scene"]["target_object_id"] == "1"
    assert (cache / "bundles" / f"{case_id}.json").exists()


def test_analyze_rejects_a_wrong_agent_verdict(case):
    case_id, cache = case
    _cache_agent_run(cache, case_id, "PERCEPTION_LATE")
    verdict = an.analyze(case_id)["verdict"]
    assert verdict["status"] == "REJECTED"
    assert verdict["independent_label"] == "BRAKE_ACTUATION_LATE"
