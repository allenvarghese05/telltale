import json

import pytest

import telltale.video.report as rep
from telltale.config import CACHE
from telltale.core.manifest import DEFAULT_POLYGON
from telltale.video.report import build_video_report

CAND38 = {"clip_id": "cand38", "time_of_event": 8.0, "ego_lane_polygon": DEFAULT_POLYGON}


def _cand38_tracks():
    return json.loads((CACHE / "sam" / "cand38.json").read_text())


def _cand38_witness():
    return json.loads((CACHE / "witness" / "cand38.json").read_text())["answers"]


def test_report_covers_what_the_video_alone_can_establish():
    report = build_video_report(_cand38_tracks(), CAND38, _cand38_witness())
    assert report["clip_id"] == "cand38"
    assert report["tracked_vehicles"] == 16
    assert report["struck_vehicle"] == "3"
    assert report["hazard_onset"]["reason"] == "closing"
    assert report["hazard_onset"]["warning_s"] == pytest.approx(8.0 - report["hazard_onset"]["t"])
    assert report["conditions"]["lighting"] == "daylight"


def test_timeline_is_in_time_order_and_ends_at_impact():
    timeline = build_video_report(_cand38_tracks(), CAND38, None)["timeline"]
    times = [e["t"] for e in timeline]
    assert times == sorted(times)
    assert timeline[-1] == {"t": 8.0, "event": "impact"}


def test_summary_is_plain_english_with_numbers_from_the_scene():
    report = build_video_report(_cand38_tracks(), CAND38, _cand38_witness())
    onset = report["hazard_onset"]
    assert report["summary"][0] == "SAM 3.1 tracked 16 vehicles."
    assert f"became a hazard at {onset['t']:.2f} s" in report["summary"][1]
    assert f"{onset['warning_s']:.2f} s before the impact at 8.00 s" in report["summary"][1]
    assert "Witness (Muse Spark): lighting daylight, weather overcast, road dry." in report["summary"]


def test_report_never_claims_a_cause():
    report = build_video_report(_cand38_tracks(), CAND38, None)
    assert "CAN and ADAS logs" in report["attribution"]
    assert "telltale analyze" in report["attribution"]
    banned = ("fault", "blame", "liab", "negligen")
    assert not any(word in sentence.lower() for sentence in report["summary"] for word in banned)


def test_a_struck_vehicle_that_never_became_a_hazard_is_reported_as_such():
    still = [{"frame": f, "box": [600.0, 500.0, 700.0, 575.0]} for f in range(260)]
    tracks = {"fps": 30.0, "width": 1280, "height": 720, "objects": {"1": still}}
    report = build_video_report(tracks, CAND38, None)
    assert report["hazard_onset"] is None
    assert any("never registered as a hazard" in s for s in report["summary"])


def test_video_report_explains_how_to_get_tracks_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(rep, "CACHE", tmp_path)
    monkeypatch.setattr(rep, "get_clip", lambda _clip_id: CAND38)
    with pytest.raises(FileNotFoundError, match="telltale sam cand38"):
        rep.video_report("cand38")


def _report_for(clip_id):
    tracks = json.loads((CACHE / "sam" / f"{clip_id}.json").read_text())
    return build_video_report(
        tracks, {"clip_id": clip_id, "time_of_event": 8.0, "ego_lane_polygon": DEFAULT_POLYGON}, None
    )


def test_a_cross_path_crash_is_labelled_honestly():
    """cand60: an oncoming car turning across our path. The report must not imply a forward conflict."""
    report = _report_for("cand60")
    assert report["struck_vehicle_geometry"] == "side_or_crossing"
    assert any("across our path" in s for s in report["summary"])


def test_a_rear_end_carries_no_geometry_caveat():
    report = _report_for("cand36")
    assert report["struck_vehicle_geometry"] == "ahead_in_lane"
    assert not any("across our path" in s for s in report["summary"])


def test_a_collision_course_onset_is_explained_in_the_report():
    report = _report_for("cand14")
    assert report["struck_vehicle"] == "4"
    assert report["hazard_onset"]["reason"] == "collision_course"
