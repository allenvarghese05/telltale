"""Draw the ego-lane polygon on a frame so a human can tune it per clip."""

from __future__ import annotations

import cv2
import numpy as np

from telltale.config import CACHE, CLIPS
from telltale.core.manifest import get_clip


def lane_preview(clip_id: str) -> str:
    clip = get_clip(clip_id)
    cap = cv2.VideoCapture(str(CLIPS / clip["file"]))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, clip["time_of_event"] - 1.0) * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"{clip_id}: could not read a frame near {clip['time_of_event']}s")
    h, w = frame.shape[:2]
    pts = np.array([[int(x * w), int(y * h)] for x, y in clip["ego_lane_polygon"]], np.int32)
    cv2.polylines(frame, [pts], True, (255, 200, 0), 3)
    out = CACHE / "previews" / f"{clip_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), frame)
    return str(out)
