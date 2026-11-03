"""Download, trim and register real crash clips from the Nexar Collision Prediction Dataset.

Dataset layout, verified against the live repository on 2026-11-02: positives and negatives live in
separate folders (`train/positive/`, `train/negative/`), each with its own `metadata.csv`. There is
no `label` column — the folder is the label — and the id column is `file_name` (e.g. `00822.mp4`).
"""

from __future__ import annotations

import csv
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

import cv2
import imageio_ffmpeg
from huggingface_hub import hf_hub_download

from telltale.config import CLIPS, DATA
from telltale.core.manifest import DEFAULT_POLYGON, load_manifest, save_manifest

REPO = "nexar-ai/nexar_collision_prediction"
POSITIVE_DIR = "train/positive"
METADATA_CSV = f"{POSITIVE_DIR}/metadata.csv"
ID_COLUMN = "file_name"
RAW = DATA / "nexar_raw"
PRE_S, POST_S = 8.0, 1.5


def _f(x: str | None) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_positive_rows(rows: Iterable[dict]) -> list[dict]:
    """Keep the rows that carry an event time, which is every annotated crash in the positive split."""
    clips = []
    for row in rows:
        if ID_COLUMN not in row:
            raise KeyError(f"{METADATA_CSV} has no {ID_COLUMN!r} column, found {sorted(row)}")
        event = _f(row.get("time_of_event"))
        if event is None:
            continue
        clips.append(
            {
                "nexar_id": row[ID_COLUMN].replace(".mp4", ""),
                "time_of_event": event,
                "time_of_alert": _f(row.get("time_of_alert")),
                "scene": row.get("scene", ""),
                "weather": row.get("weather", ""),
                "light": row.get("light_conditions", ""),
            }
        )
    return clips


def _metadata_csv() -> Path:
    return Path(hf_hub_download(REPO, METADATA_CSV, repo_type="dataset", local_dir=RAW))


def positive_clips() -> list[dict]:
    with _metadata_csv().open(newline="") as fh:
        return parse_positive_rows(csv.DictReader(fh))


def format_positive_clips(clips: list[dict]) -> list[str]:
    """One tab-separated line per clip, for the `telltale fetch-list` curation step."""
    lines = []
    for c in clips:
        alert = "none" if c["time_of_alert"] is None else f"{c['time_of_alert']:.2f}s"
        lines.append(
            f"{c['nexar_id']}\tevent={c['time_of_event']:.2f}s\talert={alert}"
            f"\t{c['scene']}\t{c['weather']}\t{c['light']}"
        )
    return lines


def print_positive_clips() -> None:
    """CLI output for `telltale fetch-list`."""
    for line in format_positive_clips(positive_clips()):
        print(line)


def _video_path(nexar_id: str) -> str:
    return f"{POSITIVE_DIR}/{nexar_id}.mp4"


def transcode(src: Path, dst: Path, start: float | None = None, duration: float | None = None) -> None:
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True, capture_output=True)


def _probe(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    probed = {
        "fps": float(cap.get(cv2.CAP_PROP_FPS)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    return probed


def fetch_trimmed(meta: dict, dest_dir: Path, name: str, delete_raw: bool = False) -> dict:
    """Download one Nexar clip, trim to [event-8s, event+1.5s], return a ClipEntry (no manifest write)."""
    raw = Path(hf_hub_download(REPO, _video_path(meta["nexar_id"]), repo_type="dataset", local_dir=RAW))
    start = max(0.0, meta["time_of_event"] - PRE_S)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / f"{name}.mp4"
    transcode(raw, dst, start, (meta["time_of_event"] - start) + POST_S)
    if delete_raw:
        raw.unlink(missing_ok=True)
    alert = meta.get("time_of_alert")
    return {
        "clip_id": name,
        "nexar_id": meta["nexar_id"],
        "file": dst.name,
        **_probe(dst),
        "time_of_event": round(meta["time_of_event"] - start, 3),
        "time_of_alert": None if alert is None else round(alert - start, 3),
        "ego_lane_polygon": DEFAULT_POLYGON,
    }


def fetch_clip(nexar_id: str, clip_id: str) -> dict:
    matches = [c for c in positive_clips() if c["nexar_id"] == nexar_id]
    if not matches:
        raise KeyError(f"{nexar_id} is not an annotated crash clip in {METADATA_CSV}")
    entry = fetch_trimmed(matches[0], CLIPS, clip_id)
    manifest = load_manifest()
    manifest["clips"][clip_id] = entry
    save_manifest(manifest)
    return entry


def add_clip(path: str, clip_id: str, event_time: float) -> dict:
    """Bring-your-own dashcam clip: re-encode to H.264, register with the impact time you provide."""
    CLIPS.mkdir(parents=True, exist_ok=True)
    dst = CLIPS / f"{clip_id}.mp4"
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
    manifest = load_manifest()
    manifest["clips"][clip_id] = entry
    save_manifest(manifest)
    return entry


def copy_license() -> None:
    lic = Path(hf_hub_download(REPO, "LICENSE", repo_type="dataset", local_dir=RAW))
    CLIPS.mkdir(parents=True, exist_ok=True)
    shutil.copy(lic, CLIPS / "NEXAR_LICENSE")
