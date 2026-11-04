"""Bring your own dashcam clip: register it, track it with SAM 3.1, ask the Muse Spark witness, report on it.

The result is a video-only bundle the static site shows on its own page. It describes what the footage alone
establishes and never carries a verdict: whether the vehicle's systems responded in time needs its CAN and ADAS
logs, which a dashcam clip does not have. The impact time is always given by the person, never inferred.

Every step is injectable, so the CLI and the local upload page share this one function and tests run without
the network.

A person's own clips never touch tracked files. They are registered under `data/uploads/` (git-ignored) with their
own manifest, tracks, witness answers and bundles, and the hosted site's export never reads that folder.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import cv2

from telltale.config import CACHE, DATA
from telltale.core.manifest import DEFAULT_POLYGON, load_manifest, save_manifest
from telltale.data.fetch import transcode
from telltale.video.report import build_video_report
from telltale.video.sam import SCRIPT as SAM_SCRIPT
from telltale.video.sam import run_sam
from telltale.video.witness import PROMPT, _ask_video, parse_witness_json

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
VIDEO_SUFFIXES = (".mp4", ".mov")
STEPS = (
    ("prepare", "Preparing the clip"),
    ("track", "Tracking vehicles with SAM 3.1"),
    ("witness", "Asking the Muse Spark witness"),
    ("report", "Building the report"),
)
UPLOADS = DATA / "uploads"
SHOWCASE_BUNDLES = CACHE / "video_bundles"


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


def _probe(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    probed = {
        "fps": float(cap.get(cv2.CAP_PROP_FPS)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    return probed


def upload_entry(clip_id: str, root: Path = UPLOADS) -> dict:
    """One uploaded clip's manifest entry, from the uploads manifest only."""
    clips = load_manifest(root / "manifest.json")["clips"]
    if clip_id not in clips:
        raise ClipInputError(f"No uploaded clip named {clip_id!r}. Upload it first.")
    return clips[clip_id]


def taken_clip_ids(root: Path = UPLOADS) -> set[str]:
    """Ids already used by the committed demo clips or by earlier uploads."""
    return set(load_manifest()["clips"]) | set(load_manifest(root / "manifest.json")["clips"])


def register_upload(path: Path, clip_id: str, event_time: float, root: Path = UPLOADS) -> dict:
    """Re-encode a person's clip to H.264 and register it in the uploads manifest, never the committed one."""
    dst = root / "clips" / f"{clip_id}.mp4"
    dst.parent.mkdir(parents=True, exist_ok=True)
    transcode(Path(path), dst)
    entry = {
        "clip_id": clip_id,
        "nexar_id": None,
        "file": dst.name,
        **_probe(dst),
        "time_of_event": event_time,
        "time_of_alert": None,
        "ego_lane_polygon": DEFAULT_POLYGON,
    }
    manifest = load_manifest(root / "manifest.json")
    manifest["clips"][clip_id] = entry
    save_manifest(manifest, root / "manifest.json")
    return entry


def track_upload(clip_id: str, root: Path = UPLOADS) -> str:
    """SAM 3.1 tracks for an uploaded clip, written under the uploads folder."""
    clip = upload_entry(clip_id, root)
    out = root / "sam" / f"{clip_id}.json"
    return str(run_sam(root / "clips" / clip["file"], out, clip["fps"], clip["width"], clip["height"]))


def witness_upload(clip_id: str, root: Path = UPLOADS) -> dict:
    """The Muse Spark witness on an uploaded clip, its answers kept under the uploads folder."""
    clip = upload_entry(clip_id, root)
    answers = parse_witness_json(_ask_video(root / "clips" / clip["file"], PROMPT))
    out = root / "witness" / f"{clip_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"answers": answers}, indent=2))
    return answers


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
    register: Callable[[str, str, float], dict] = register_upload,
    track: Callable[[str], str] = track_upload,
    ask_witness: Callable[[str], dict] = witness_upload,
    cookbook: Path = SAM_SCRIPT,
    bundle_dir: Path = UPLOADS / "video_bundles",
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
