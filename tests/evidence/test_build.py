import pytest

from telltale.core.schema import Fact, VideoFacts
from telltale.evidence.build import build_store
from telltale.logs.generate import CONFUSABLE_EXPECTED, EXPECTED, ClipTiming, generate_case
from telltale.physics.profiles import PROFILES

TIMING = ClipTiming(clip_id="syn", hazard_onset_t=4.0, impact_t=6.2)
VIDEO = VideoFacts(
    clip_id="syn",
    fps=30.0,
    hazard_onset_t=4.0,
    hazard_onset_reason="entering",
    impact_t=6.2,
    ttc_at_onset=1.9,
    target_object_id="1",
)


@pytest.mark.parametrize("profile", ["car", "truck"])
@pytest.mark.parametrize("story", list(EXPECTED))
def test_engine_recovers_the_injected_story_blind(tmp_path, profile, story):
    cid = generate_case(TIMING, PROFILES[profile], story, seed=11, out_root=tmp_path / "c", gt_root=tmp_path / "g")
    store = build_store(tmp_path / "c" / cid, VIDEO, PROFILES[profile])
    assert store.get("ATTR:label").value == EXPECTED[story]
    assert store.verify_integrity()


def test_store_contains_core_facts_and_extra_witness_facts(tmp_path):
    cid = generate_case(
        TIMING, PROFILES["car"], "perception_late", seed=5, out_root=tmp_path / "c", gt_root=tmp_path / "g"
    )
    wit = [Fact("WIT:other_vehicle_turn_signal", "no", "", "WIT", "spark", "observation")]
    s = build_store(tmp_path / "c" / cid, VIDEO, PROFILES["car"], extra_facts=wit)
    for fid in [
        "VID:hazard_onset_t",
        "VID:hazard_onset_reason",
        "AV:first_seen_t",
        "CAN:brake_request_t",
        "PHYS:perception_latency_s",
        "PHYS:cf_nominal_contact",
        "PROFILE:perception_threshold_s",
        "DATA:brake_log_complete",
        "WIT:other_vehicle_turn_signal",
        "PHYS:gap_at_onset_m",
        "CAN:speed_at_onset_mps",
    ]:
        assert s.has(fid), fid
    assert s.get("PHYS:perception_latency_s").value > 0.9
    assert "can.speed_mps" in s.series_names()


@pytest.mark.parametrize("story", list(CONFUSABLE_EXPECTED))
def test_engine_reads_confusable_timelines_blind(tmp_path, story):
    cid = generate_case(TIMING, PROFILES["car"], story, seed=5, out_root=tmp_path / "c", gt_root=tmp_path / "g")
    store = build_store(tmp_path / "c" / cid, VIDEO, PROFILES["car"])
    assert store.get("ATTR:label").value == CONFUSABLE_EXPECTED[story]
    assert store.has("AV:brake_request_t") == (story == "adas_brake_then_handoff")
    assert store.has("AV:handoff_t") == story.startswith(("handoff", "adas_brake"))
    assert store.has("CAN:brake_request_t")
