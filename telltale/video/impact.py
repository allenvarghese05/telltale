"""Suggest when the impact happened in an uploaded clip, for a person to confirm or correct.

An uploaded clip has no labelled event time, but every video fact is measured relative to one. Two deterministic
signals are offered, and only ever as a prefilled, editable value:

- the **camera jolt**: the frame where the picture changes most from one frame to the next, which a collision
  causes by shaking the camera;
- with tracks only, the frame where a tracked vehicle **looms largest** (its box is tallest), which is when it
  is closest.

Measured on the 400 Nexar clips of the A5 benchmark, each evaluated inside a random window containing the labelled
event, so its position in the clip gives nothing away: the jolt lands within 0.5 s of Nexar's time_of_event on
54.5% of clips and within 1 s on 67.2%; box height on 49.2% and 65.5%; a no-information guess on 1.2% and 16.2%.
See docs/benchmarks/a5-scale-results.md.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

JOLT_SIZE = (160, 90)


def jolt_series(video_path: Path) -> tuple[np.ndarray, float]:
    """Mean absolute grey-level change between consecutive frames, downscaled, and the clip's frame rate."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    jolt, prev = [], None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        grey = cv2.cvtColor(cv2.resize(frame, JOLT_SIZE), cv2.COLOR_BGR2GRAY).astype(np.float32)
        jolt.append(0.0 if prev is None else float(np.mean(np.abs(grey - prev))))
        prev = grey
    cap.release()
    return np.array(jolt), fps


def impact_from_jolt(jolt: np.ndarray, fps: float) -> float | None:
    """The time of the largest frame-to-frame change; None when nothing in the clip moves."""
    if len(jolt) == 0 or float(np.max(jolt)) <= 0.0:
        return None
    return float(np.argmax(jolt)) / fps


def impact_from_tracks(tracks: dict) -> float | None:
    """The time at which any tracked vehicle's box is tallest, i.e. closest to the camera."""
    best = None
    for dets in tracks["objects"].values():
        for d in dets:
            height = d["box"][3] - d["box"][1]
            if best is None or height > best[0]:
                best = (height, d["frame"])
    return None if best is None else best[1] / tracks["fps"]


def suggest_impact_time(video_path: Path | None = None, tracks: dict | None = None) -> float | None:
    """A suggested impact time in seconds, from the video if given (more accurate), else from SAM tracks."""
    if video_path is None and tracks is None:
        raise ValueError("suggest_impact_time needs a video path or tracks")
    if video_path is not None:
        jolt, fps = jolt_series(Path(video_path))
        return impact_from_jolt(jolt, fps)
    return impact_from_tracks(tracks)
