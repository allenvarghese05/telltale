"""Bring your own dashcam clip: register it, track it with SAM 3.1, ask the Muse Spark witness, report on it.

The result is a video-only bundle the static site shows on its own page. It describes what the footage alone
establishes and never carries a verdict: whether the vehicle's systems responded in time needs its CAN and ADAS
logs, which a dashcam clip does not have. The impact time is always given by the person, never inferred.

Every step is injectable, so the CLI and the local upload page share this one function and tests run without
the network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import cv2

from telltale.config import CACHE
from telltale.data.fetch import add_clip
from telltale.video.report import build_video_report
from telltale.video.sam import SCRIPT as SAM_SCRIPT
from telltale.video.sam import run_sam_for_clip
from telltale.video.witness import run_witness_for_clip

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
VIDEO_SUFFIXES = (".mp4", ".mov")
STEPS = (
    ("prepare", "Preparing the clip"),
    ("track", "Tracking vehicles with SAM 3.1"),
    ("witness", "Asking the Muse Spark witness"),
    ("report", "Building the report"),
)
BUNDLES = CACHE / "video_bundles"


class ClipInputError(ValueError):
    """An input the person can fix; the message says how."""


def clip_duration(path: Path) -> float:
    """Length of a video in seconds, from its frame count and frame rate."""
    cap = cv2.VideoCapture(str(path))
    frames, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    if not fps or not frames:
        raise ClipInputError(f"Could not read {path.name} as a video. Re-export it as H.264 .mp4 and try again.")
    return float(frames) / float(fps)


def check_clip_id(clip_id: str) -> None:
    if not SAFE_ID.match(clip_id):
        raise ClipInputError(
            f"Clip id {clip_id!r} is not allowed. Use only letters, digits, hyphens and underscores, e.g. my-clip_01."
        )


def check_inputs(path: Path, clip_id: str, event_time: float, cookbook: Path, duration: Callable) -> None:
    """Fail before any work is done, with a message that says what to change."""
    check_clip_id(clip_id)
    if not path.is_file():
        raise ClipInputError(f"No video file at {path}. Check the path and try again.")
    if path.suffix.lower() not in VIDEO_SUFFIXES:
        raise ClipInputError(f"{path.name} must be an .mp4 or .mov file.")
    length = duration(path)
    if not 0.0 < event_time <= length:
        raise ClipInputError(
            f"Impact time {event_time:.2f} s is outside the clip, which is {length:.2f} s long. "
            "Give the time of impact in seconds from the start of the video."
        )
    if not cookbook.is_file():
        raise ClipInputError(
            "The SAM 3.1 cookbook script is missing. Fetch it once with "
            "`git clone --depth 1 https://github.com/meta-models/meta-model-cookbook vendor/meta-model-cookbook`, "
            "as described under 'On any dashcam clip' in the README."
        )


def video_bundle(clip: dict, tracks: dict, report: dict) -> dict:
    """What the site's video-only page needs: the footage, every SAM track, and the report. No verdict."""
    return {
        "clip_id": clip["clip_id"],
        "video_url": f"media/{clip['file']}",
        "fps": clip["fps"],
        "width": clip["width"],
        "height": clip["height"],
        "lane_polygon": clip["ego_lane_polygon"],
        "tracks": {
            oid: [[d["frame"], *(round(v) for v in d["box"])] for d in dets] for oid, dets in tracks["objects"].items()
        },
        "report": report,
    }


def investigate_clip(
    path: Path,
    clip_id: str,
    event_time: float,
    progress: Callable[[str], None] | None = None,
    *,
    duration: Callable[[Path], float] = clip_duration,
    register: Callable[[str, str, float], dict] = add_clip,
    track: Callable[[str], str] = run_sam_for_clip,
    ask_witness: Callable[[str], dict] = run_witness_for_clip,
    cookbook: Path = SAM_SCRIPT,
    bundle_dir: Path = BUNDLES,
) -> dict:
    """Run one clip end to end and write `<bundle_dir>/<clip_id>.json`. Returns the bundle."""
    path = Path(path)
    check_inputs(path, clip_id, event_time, cookbook, duration)
    say = progress or (lambda _step: None)
    say("prepare")
    clip = register(str(path), clip_id, event_time)
    say("track")
    tracks = json.loads(Path(track(clip_id)).read_text())
    say("witness")
    answers = ask_witness(clip_id)
    say("report")
    bundle = video_bundle(clip, tracks, build_video_report(tracks, clip, answers))
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / f"{clip_id}.json").write_text(json.dumps(bundle))
    return bundle
