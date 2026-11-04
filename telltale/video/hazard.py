"""When did each tracked vehicle become a hazard to the ego car?

Earlier versions examined only the struck vehicle, chosen as the largest box near impact. That is a sound
way to find *what was hit*, but a poor way to find *when the danger started*: on a real clip one car moves
into the ego lane while another leaves it, and only looking at the biggest box hides that. Every tracked
object is assessed here, and each can become a hazard in one of four ways:

- `entering` — it crosses laterally into the ego lane;
- `predicted` — it is still outside the lane but closing on the edge fast enough to arrive within
  `DANGER_TLC_S`, which is when a cut-in becomes foreseeable rather than when it lands;
- `closing` — it is already in the ego lane and the time to collision stays under `DANGER_TTC_S`;
- `collision_course` — wherever it is, it is closing on the ego car fast while touching the ego lane's extent,
  which catches a car turning across our path or striking our side (see `lane.collision_course_frame`).

A vehicle is only ever a hazard while it is actually approaching, so each reason also requires a finite
time to collision. A car in the next lane travelling alongside raises nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from telltale.video.lane import (
    collision_course_frame,
    lane_entry_frame,
    lane_overlap_fraction,
    lane_polygon_px,
    resolvable,
)
from telltale.video.motion import lateral_offsets, lateral_rate, time_to_lane_crossing
from telltale.video.ttc import first_sustained_below, ttc_series

DANGER_TTC_S = 2.0
DANGER_TLC_S = 2.0
MAX_LANES_AWAY = 2.5
MIN_DETECTIONS = 20
HOLD_FRAMES = 9
MIN_IN_LANE_FRACTION = 0.5


@dataclass(frozen=True)
class HazardOnset:
    object_id: str
    onset_t: float
    reason: str
    u_at_onset: float | None
    ttc_at_onset: float | None


def _first_predicted_crossing(
    frames: np.ndarray, offsets: np.ndarray, rate: np.ndarray, fps: float, closing: np.ndarray
) -> int | None:
    run = 0
    for i in range(len(frames)):
        imminent = closing[i] and time_to_lane_crossing(float(offsets[i]), float(rate[i])) <= DANGER_TLC_S
        run = run + 1 if imminent else 0
        if run >= HOLD_FRAMES:
            return int(frames[i - HOLD_FRAMES + 1])
    return None


def hazard_onsets(tracks: dict, clip: dict) -> list[HazardOnset]:
    """Every tracked vehicle that became a hazard, earliest first."""
    fps = tracks["fps"]
    poly = lane_polygon_px(tracks, clip)
    impact_t = float(clip["time_of_event"])
    found: list[HazardOnset] = []

    for oid, raw in tracks["objects"].items():
        dets = sorted(raw, key=lambda d: d["frame"])
        if len(dets) < MIN_DETECTIONS:
            continue
        ttc_frames, ttc = ttc_series(dets, fps)
        by_frame = {int(f): ttc[i] for i, f in enumerate(ttc_frames)}

        # Lane-agnostic, so it runs on the raw boxes before any test that needs a lane position.
        candidates: list[tuple[int, str]] = []
        course = collision_course_frame(dets, fps, poly, tracks["width"])
        if course is not None:
            candidates.append((course, "collision_course"))

        frames, offsets = lateral_offsets(dets, poly)
        fitted = None
        if len(frames) >= MIN_DETECTIONS:
            rate, fitted, _ = lateral_rate(frames, offsets, fps)
            closing = np.array([np.isfinite(by_frame.get(int(f), np.inf)) for f in frames])
            entry = lane_entry_frame(dets, poly)
            if entry is not None:
                candidates.append((entry, "entering"))
            predicted = _first_predicted_crossing(frames, fitted, rate, fps, closing)
            if predicted is not None:
                candidates.append((predicted, "predicted"))
            by_frame_box = {int(d["frame"]): d["box"] for d in dets}
            in_lane = np.array(
                [
                    lane_overlap_fraction(by_frame_box[int(f)], poly) >= MIN_IN_LANE_FRACTION
                    and resolvable(by_frame_box[int(f)], tracks["width"])
                    for f in frames
                ]
            )
            masked = np.where(in_lane, [by_frame.get(int(f), np.inf) for f in frames], np.inf)
            closing_frame = first_sustained_below(frames, masked, DANGER_TTC_S, HOLD_FRAMES)
            if closing_frame is not None:
                candidates.append((closing_frame, "closing"))
        lane_based = [c for c in candidates if c[1] != "collision_course"]
        if lane_based:
            candidates = lane_based
        if not candidates:
            continue

        frame, reason = min(candidates)
        onset_t = frame / fps
        if onset_t > impact_t:
            continue
        u_at_onset = None
        if fitted is not None:
            index = int(np.argmin(np.abs(frames - frame)))
            u_at_onset = float(fitted[index])
            if reason != "collision_course" and abs(u_at_onset - 0.5) > MAX_LANES_AWAY:
                continue
        value = by_frame.get(frame)
        found.append(
            HazardOnset(
                object_id=oid,
                onset_t=onset_t,
                reason=reason,
                u_at_onset=u_at_onset,
                ttc_at_onset=float(value) if value is not None and np.isfinite(value) else None,
            )
        )
    return sorted(found, key=lambda h: h.onset_t)
