import numpy as np
import pytest

from telltale.video.impact import impact_from_jolt, impact_from_tracks, suggest_impact_time


def test_the_impact_is_the_biggest_camera_jolt():
    jolt = np.full(300, 2.0)
    jolt[240] = 25.0
    assert impact_from_jolt(jolt, fps=30.0) == pytest.approx(8.0)


def test_a_clip_with_no_motion_has_no_suggestion():
    assert impact_from_jolt(np.zeros(300), fps=30.0) is None


def test_from_tracks_the_impact_is_where_a_vehicle_looms_largest():
    dets = [{"frame": f, "box": [600.0, 400.0 - f, 700.0, 450.0 + f]} for f in range(200)]
    dets += [{"frame": f, "box": [600.0, 200.0, 700.0, 650.0]} for f in range(200, 260)]
    tracks = {"fps": 30.0, "width": 1280, "height": 720, "objects": {"1": dets}}
    assert impact_from_tracks(tracks) == pytest.approx(200 / 30.0, abs=0.05)


def test_suggest_needs_a_video_or_tracks():
    with pytest.raises(ValueError, match="a video path or tracks"):
        suggest_impact_time()


def test_suggest_prefers_the_video_when_both_are_given(tmp_path, monkeypatch):
    import telltale.video.impact as impact

    monkeypatch.setattr(impact, "jolt_series", lambda _path: (np.full(300, 1.0) + (np.arange(300) == 120) * 20, 30.0))
    tracks = {"fps": 30.0, "width": 1280, "height": 720, "objects": {}}
    assert suggest_impact_time(video_path=tmp_path / "clip.mp4", tracks=tracks) == pytest.approx(4.0)
