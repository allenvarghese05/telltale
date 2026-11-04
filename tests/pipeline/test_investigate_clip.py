import json

import pytest

from telltale.pipeline.investigate_clip import STEPS, ClipInputError, investigate_clip

CLIP = {
    "clip_id": "mine",
    "nexar_id": None,
    "file": "mine.mp4",
    "fps": 30.0,
    "width": 1280,
    "height": 720,
    "time_of_event": 7.4,
    "time_of_alert": None,
    "ego_lane_polygon": [[0.4, 0.62], [0.6, 0.62], [0.85, 1.0], [0.15, 1.0]],
}
TRACKS = {
    "fps": 30.0,
    "width": 1280,
    "height": 720,
    "objects": {"3": [{"frame": 0, "box": [600.4, 380.6, 700.2, 450.9]}]},
}
ANSWERS = {"lighting": "daylight", "weather": "clear", "road_surface": "dry"}


@pytest.fixture
def env(tmp_path):
    video = tmp_path / "dashcam.mp4"
    video.write_bytes(b"\x00")
    cookbook = tmp_path / "segment_video.py"
    cookbook.write_text("")
    calls = []

    def register(path, clip_id, event_time):
        calls.append(("register", clip_id, event_time))
        return {**CLIP, "clip_id": clip_id, "time_of_event": event_time}

    def track(clip_id):
        calls.append(("track", clip_id))
        out = tmp_path / f"{clip_id}.tracks.json"
        out.write_text(json.dumps(TRACKS))
        return str(out)

    def ask_witness(clip_id):
        calls.append(("witness", clip_id))
        return ANSWERS

    def run(path=video, clip_id="mine", event_time=7.4, progress=None):
        return investigate_clip(
            path,
            clip_id,
            event_time,
            progress=progress,
            duration=lambda _: 9.5,
            register=register,
            track=track,
            ask_witness=ask_witness,
            cookbook=cookbook,
            bundle_dir=tmp_path / "video_bundles",
        )

    return {"run": run, "calls": calls, "tmp": tmp_path, "video": video, "cookbook": cookbook}


def test_chains_every_step_in_order_and_reports_progress(env):
    seen = []
    env["run"](progress=seen.append)
    assert env["calls"] == [("register", "mine", 7.4), ("track", "mine"), ("witness", "mine")]
    assert seen == [key for key, _ in STEPS]


def test_writes_a_video_only_bundle_the_site_can_show(env):
    bundle = env["run"]()
    on_disk = json.loads((env["tmp"] / "video_bundles" / "mine.json").read_text())
    assert on_disk == bundle
    assert bundle["clip_id"] == "mine"
    assert bundle["video_url"] == "media/mine.mp4"
    assert bundle["tracks"] == {"3": [[0, 600, 381, 700, 451]]}
    assert bundle["report"]["conditions"] == ANSWERS
    assert bundle["report"]["impact_t"] == 7.4


def test_a_video_only_bundle_never_carries_a_verdict(env):
    bundle = env["run"]()
    assert not {"verdict", "claims", "counts", "counterfactual_inputs", "facts"} & set(bundle)
    assert bundle["report"]["attribution"].startswith("Not determined from video alone")


def test_unsafe_clip_id_is_rejected_before_anything_runs(env):
    with pytest.raises(ClipInputError, match="letters, digits, hyphens and underscores"):
        env["run"](clip_id="../evil")
    assert env["calls"] == []


def test_missing_video_file_is_rejected(env):
    with pytest.raises(ClipInputError, match="No video file at"):
        env["run"](path=env["tmp"] / "nope.mp4")
    assert env["calls"] == []


def test_unsupported_video_type_is_rejected(env):
    avi = env["tmp"] / "dashcam.avi"
    avi.write_bytes(b"\x00")
    with pytest.raises(ClipInputError, match=r"must be an \.mp4 or \.mov file"):
        env["run"](path=avi)


@pytest.mark.parametrize("event_time", [-0.5, 0.0, 9.6, 12.0])
def test_event_time_outside_the_clip_is_rejected(env, event_time):
    with pytest.raises(ClipInputError, match=r"outside the clip, which is 9\.50 s long"):
        env["run"](event_time=event_time)
    assert env["calls"] == []


def test_missing_sam_cookbook_points_to_the_setup_step(env):
    env["cookbook"].unlink()
    with pytest.raises(ClipInputError, match=r"SAM 3\.1 cookbook script is missing.*vendor/meta-model-cookbook"):
        env["run"]()
    assert env["calls"] == []
