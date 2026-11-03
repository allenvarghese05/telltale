"""SAM 3.1 video tracking via the vendored Meta cookbook script, normalized to our track format."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from telltale.config import CACHE, CLIPS, ROOT
from telltale.core.manifest import get_clip

SCRIPT = ROOT / "vendor/meta-model-cookbook/07_sam/01_api_basics/python/02_upload_and_segment_video.py"


def normalize_sam_summary(summary: list | dict, fps: float, width: int, height: int) -> dict:
    """Group the cookbook's flat box list by object id, drop frameless boxes, scale to pixels.

    The parser documents its boxes as source-media coordinates, so they arrive in pixels; the
    fractional branch is a guard in case a future API revision switches to 0-1 coordinates.
    """
    results = summary if isinstance(summary, list) else [summary]
    boxes = [b for b in results[0]["boxes"] if b.get("frame") is not None]
    fractional = bool(boxes) and max(max(b["left"], b["top"], b["right"], b["bottom"]) for b in boxes) <= 1.0
    sx, sy = (width, height) if fractional else (1, 1)
    objects: dict[str, list[dict]] = {}
    for b in boxes:
        box = [float(b["left"]) * sx, float(b["top"]) * sy, float(b["right"]) * sx, float(b["bottom"]) * sy]
        objects.setdefault(str(b["object_id"]), []).append({"frame": int(b["frame"]), "box": box})
    for dets in objects.values():
        dets.sort(key=lambda d: d["frame"])
    return {"fps": fps, "width": width, "height": height, "objects": objects}


def run_sam(video: Path, out_json: Path, fps: float, width: int, height: int, concept: str = "car") -> Path:
    raw_dir = CACHE / "sam_raw" / out_json.stem
    try:
        subprocess.run(
            [sys.executable, str(SCRIPT), str(video), "--concept", concept, "--output", str(raw_dir)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"SAM failed on {video.name}: {exc.stderr.decode(errors='replace')[-500:]}") from exc
    tracks = normalize_sam_summary(json.loads((raw_dir / "summary.json").read_text()), fps, width, height)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(tracks))
    return out_json


def run_sam_for_clip(clip_id: str, concept: str = "car") -> str:
    clip = get_clip(clip_id)
    return str(
        run_sam(
            CLIPS / clip["file"],
            CACHE / "sam" / f"{clip_id}.json",
            clip["fps"],
            clip["width"],
            clip["height"],
            concept,
        )
    )
