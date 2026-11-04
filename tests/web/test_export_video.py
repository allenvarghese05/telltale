import json
import re
from pathlib import Path

import pytest

from telltale.web import export as export_module
from telltale.web.export import export_site, publish_video_case

VIDEO = {
    "clip_id": "cand60",
    "video_url": "media/cand60.mp4",
    "fps": 30.0,
    "width": 1280,
    "height": 720,
    "lane_polygon": [[0.4, 0.62], [0.6, 0.62], [0.85, 1.0], [0.15, 1.0]],
    "tracks": {"3": [[0, 600, 381, 700, 451]]},
    "report": {"clip_id": "cand60", "summary": ["SAM 3.1 tracked 1 vehicles."], "attribution": "Not determined"},
}
STATIC = Path(export_module.__file__).parent / "static"


def _csp(page: str) -> str:
    return re.search(r'Content-Security-Policy"\s+content="([^"]+)"', (STATIC / page).read_text()).group(1)


@pytest.fixture
def dirs(tmp_path):
    bundles, videos, clips = tmp_path / "bundles", tmp_path / "video_bundles", tmp_path / "clips"
    for d in (bundles, videos, clips):
        d.mkdir()
    (clips / "cand60.mp4").write_bytes(b"\x00")
    return {"bundles": bundles, "videos": videos, "clips": clips, "site": tmp_path / "site"}


def build(dirs):
    return export_site(
        dirs["bundles"],
        dirs["site"],
        clips_dir=dirs["clips"],
        thumbs_dir=dirs["clips"],
        video_bundles_dir=dirs["videos"],
    )


def test_video_only_cases_are_exported_on_their_own(dirs):
    (dirs["videos"] / "cand60.json").write_text(json.dumps(VIDEO))
    site = build(dirs)
    assert json.loads((site / "videos.json").read_text()) == [{"clip_id": "cand60"}]
    assert json.loads((site / "video" / "cand60.json").read_text()) == VIDEO
    assert (site / "media" / "cand60.mp4").exists()
    assert (site / "clips.html").exists()
    assert json.loads((site / "cases.json").read_text()) == []


def test_a_video_only_case_can_never_carry_a_verdict(dirs):
    smuggled = {**VIDEO, "verdict": {"status": "VERIFIED"}, "claims": [], "counts": {}, "facts": []}
    (dirs["videos"] / "cand60.json").write_text(json.dumps(smuggled))
    exported = json.loads((build(dirs) / "video" / "cand60.json").read_text())
    assert exported == VIDEO


def test_unsafe_video_clip_id_is_rejected(dirs):
    (dirs["videos"] / "x.json").write_text(json.dumps({**VIDEO, "clip_id": "../evil"}))
    with pytest.raises(ValueError, match="unsafe clip id"):
        build(dirs)


def test_no_video_bundles_still_builds_an_empty_video_page(dirs):
    site = build(dirs)
    assert json.loads((site / "videos.json").read_text()) == []


def test_publishing_one_new_video_case_adds_it_without_rebuilding(dirs):
    site = build(dirs)
    publish_video_case(VIDEO, site, clips_dir=dirs["clips"])
    publish_video_case(VIDEO, site, clips_dir=dirs["clips"])
    assert json.loads((site / "videos.json").read_text()) == [{"clip_id": "cand60"}]
    assert json.loads((site / "video" / "cand60.json").read_text()) == VIDEO


def test_video_page_uses_the_same_csp_as_the_replay_page():
    assert _csp("clips.html") == _csp("index.html")


@pytest.mark.parametrize("geometry", ["forward", "cross-path"])
def test_a_clip_can_carry_its_crash_geometry(dirs, geometry):
    (dirs["videos"] / "cand60.json").write_text(json.dumps({**VIDEO, "geometry": geometry}))
    exported = json.loads((build(dirs) / "video" / "cand60.json").read_text())
    assert exported == {**VIDEO, "geometry": geometry}


def test_an_unknown_crash_geometry_is_rejected(dirs):
    (dirs["videos"] / "cand60.json").write_text(json.dumps({**VIDEO, "geometry": "<script>"}))
    with pytest.raises(ValueError, match="unknown crash geometry"):
        build(dirs)


def test_hosted_export_never_includes_local_uploads(dirs, tmp_path):
    uploads = tmp_path / "uploads"
    (uploads / "video_bundles").mkdir(parents=True)
    (uploads / "clips").mkdir()
    (uploads / "video_bundles" / "mine.json").write_text(
        json.dumps({**VIDEO, "clip_id": "mine", "video_url": "media/mine.mp4"})
    )
    (uploads / "clips" / "mine.mp4").write_bytes(b"\x00")
    site = build(dirs)
    assert json.loads((site / "videos.json").read_text()) == []
    local = export_site(
        dirs["bundles"],
        tmp_path / "local-site",
        clips_dir=dirs["clips"],
        thumbs_dir=dirs["clips"],
        video_bundles_dir=dirs["videos"],
        uploads_dir=uploads,
    )
    assert json.loads((local / "videos.json").read_text()) == [{"clip_id": "mine"}]
    assert (local / "media" / "mine.mp4").exists()


def _build_id(page: str) -> str:
    return re.search(r'<meta name="build" content="([0-9a-f]{10})">', page).group(1)


def test_export_stamps_a_content_build_id_on_pages_and_assets(dirs):
    (dirs["videos"] / "cand60.json").write_text(json.dumps(VIDEO))
    site = build(dirs)
    index, clips = (site / "index.html").read_text(), (site / "clips.html").read_text()
    build_id = _build_id(index)
    assert _build_id(clips) == build_id
    assert f'src="app.js?v={build_id}"' in index
    assert f'href="style.css?v={build_id}"' in index
    assert f'src="clips.js?v={build_id}"' in clips


def test_build_id_changes_when_a_bundle_changes(dirs):
    (dirs["videos"] / "cand60.json").write_text(json.dumps(VIDEO))
    first = _build_id((build(dirs) / "index.html").read_text())
    assert _build_id((build(dirs) / "index.html").read_text()) == first
    (dirs["videos"] / "cand60.json").write_text(json.dumps({**VIDEO, "fps": 29.97}))
    assert _build_id((build(dirs) / "index.html").read_text()) != first
