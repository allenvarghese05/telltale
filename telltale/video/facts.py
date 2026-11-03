"""Deterministic video facts: target vehicle, lane entry, TTC and danger onset."""

from __future__ import annotations

from telltale.core.schema import VideoFacts
from telltale.video.lane import lane_entry_frame, select_target
from telltale.video.ttc import first_sustained_below, ttc_at, ttc_series

DANGER_TTC_S = 2.0


def _target(tracks: dict, clip: dict) -> tuple[float, str, list[dict], list[tuple[float, float]]]:
    fps, width, height = tracks["fps"], tracks["width"], tracks["height"]
    oid = select_target(tracks["objects"], round(clip["time_of_event"] * fps))
    dets = sorted(tracks["objects"][oid], key=lambda d: d["frame"])
    poly = [(x * width, y * height) for x, y in clip["ego_lane_polygon"]]
    return fps, oid, dets, poly


def compute_video_facts(tracks: dict, clip: dict) -> VideoFacts:
    fps, oid, dets, poly = _target(tracks, clip)
    entry_frame = lane_entry_frame(dets, poly)
    if entry_frame is None:
        raise ValueError(
            f"{clip['clip_id']}: target {oid} never crosses into the ego-lane polygon. Either it is a lead "
            f"vehicle already in lane (a rear-end, which has no lane entry — use danger_onset_t instead), "
            f"or the polygon needs adjusting; run `telltale lane-preview {clip['clip_id']}` to see which."
        )
    frames, ttc = ttc_series(dets, fps)
    return VideoFacts(
        clip_id=clip["clip_id"],
        fps=fps,
        lane_entry_t=entry_frame / fps,
        impact_t=float(clip["time_of_event"]),
        ttc_at_entry=ttc_at(frames, ttc, entry_frame),
        target_object_id=oid,
    )


def danger_onset_t(tracks: dict, clip: dict) -> float | None:
    """Earliest of: target enters the ego lane, or target TTC stays below 2 s for 3 frames."""
    fps, _, dets, poly = _target(tracks, clip)
    frames, ttc = ttc_series(dets, fps)
    candidates = [
        f for f in (lane_entry_frame(dets, poly), first_sustained_below(frames, ttc, DANGER_TTC_S)) if f is not None
    ]
    return min(candidates) / fps if candidates else None
