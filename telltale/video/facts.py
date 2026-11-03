"""Deterministic video facts for one clip: the struck vehicle and the moment it became a hazard."""

from __future__ import annotations

from telltale.core.schema import VideoFacts
from telltale.video.hazard import hazard_onsets
from telltale.video.lane import select_target


def compute_video_facts(tracks: dict, clip: dict) -> VideoFacts:
    """Facts for the struck vehicle, the one filling the frame at impact.

    Its hazard onset comes from `hazard_onsets`, the same definition the scene summary and the A5 benchmark
    use, so a cut-in (`entering`/`predicted`) and a rear-end (`closing`) are handled alike.
    """
    fps = tracks["fps"]
    target = select_target(tracks["objects"], round(clip["time_of_event"] * fps))
    onset = next((h for h in hazard_onsets(tracks, clip) if h.object_id == target), None)
    if onset is None:
        raise ValueError(
            f"{clip['clip_id']}: struck vehicle {target} never became a measurable hazard (it never entered, "
            f"approached the edge of, or closed within the ego lane). Check the lane polygon with "
            f"`telltale lane-preview {clip['clip_id']}`."
        )
    return VideoFacts(
        clip_id=clip["clip_id"],
        fps=fps,
        hazard_onset_t=onset.onset_t,
        hazard_onset_reason=onset.reason,
        impact_t=float(clip["time_of_event"]),
        ttc_at_onset=onset.ttc_at_onset,
        target_object_id=target,
    )
