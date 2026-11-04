import json
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest

from telltale.config import CLIPS, ROOT
from telltale.pipeline import investigate_clip as ic


def _tiny_video(path: Path, seconds: float = 1.0, fps: int = 10) -> Path:
    writer = imageio_ffmpeg.write_frames(str(path), (64, 48), fps=fps)
    writer.send(None)
    for _ in range(int(seconds * fps)):
        writer.send(np.zeros((48, 64, 3), np.uint8))
    writer.close()
    return path


def _tracked_clip_files() -> dict:
    return {p.name: p.stat().st_mtime_ns for p in CLIPS.iterdir() if p.is_file()}


def test_uploads_live_under_a_git_ignored_folder():
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert "data/uploads/" in ignored
    assert ic.UPLOADS == ROOT / "data" / "uploads"


def test_registering_an_upload_leaves_tracked_clip_files_untouched(tmp_path):
    before = _tracked_clip_files()
    entry = ic.register_upload(_tiny_video(tmp_path / "in.mp4"), "mine", 0.5, root=tmp_path / "uploads")
    assert _tracked_clip_files() == before
    assert (tmp_path / "uploads" / "clips" / "mine.mp4").is_file()
    saved = json.loads((tmp_path / "uploads" / "manifest.json").read_text())["clips"]["mine"]
    assert saved == entry
    assert (entry["clip_id"], entry["nexar_id"], entry["time_of_event"]) == ("mine", None, 0.5)


def test_upload_clip_ids_cover_both_manifests(tmp_path):
    ic.register_upload(_tiny_video(tmp_path / "in.mp4"), "mine", 0.5, root=tmp_path / "uploads")
    taken = ic.taken_clip_ids(root=tmp_path / "uploads")
    assert "mine" in taken
    assert "cand36" in taken


def test_an_unknown_upload_clip_is_a_clear_error(tmp_path):
    with pytest.raises(ic.ClipInputError, match="No uploaded clip named 'nope'"):
        ic.upload_entry("nope", root=tmp_path / "uploads")
