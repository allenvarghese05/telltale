"""A video-only incident report for any dashcam clip.

It describes what the footage alone establishes — which vehicles were tracked, when the struck one became a
hazard and how, its lane changes, and the witness's conditions — and makes no claim about cause. Whether the
vehicle's own systems responded in time needs its CAN and ADAS logs, which is what `telltale analyze` adds.
Because it never touches the physics, it works on any crash geometry, including cross-path crashes the
1-D simulator cannot model.
"""

from __future__ import annotations

import json

from telltale.config import CACHE
from telltale.core.manifest import get_clip
from telltale.core.schema import HAZARD_REASONS
from telltale.video.lane import TARGET_MIN_LANE_OVERLAP, TARGET_WINDOW_S, lane_polygon_px, mean_lane_overlap
from telltale.video.scene import summarize_scene

CONDITION_LABELS = (("lighting", "lighting"), ("weather", "weather"), ("road_surface", "road"))
CROSSING = (
    "The struck vehicle was not ahead of us in our lane during the last second before impact: it came from the side "
    "or across our path. The lane and time-to-collision tests assume a vehicle ahead moving the same way, so the "
    "hazard onset is less certain for this geometry, and the 1-D crash physics of a full investigation cannot model it."
)
ATTRIBUTION = (
    "Not determined from video alone. Whether the vehicle's systems noticed, decided and braked in time needs "
    "its CAN and ADAS logs; run `telltale analyze` on a case that includes them."
)


def build_video_report(tracks: dict, clip: dict, witness_answers: dict | None) -> dict:
    """Everything the footage establishes about one clip, as structured fields plus plain-English sentences."""
    scene = summarize_scene(tracks, clip, witness_answers)
    impact_t = float(clip["time_of_event"])
    target = scene.target_object_id
    onset = None
    if scene.danger_onset_t is not None and scene.danger_onset_reason is not None:
        onset = {
            "t": scene.danger_onset_t,
            "reason": scene.danger_onset_reason,
            "how": HAZARD_REASONS[scene.danger_onset_reason],
            "warning_s": impact_t - scene.danger_onset_t,
        }
    changes = [
        {"start_t": c.start_t, "end_t": c.end_t, "direction": c.direction, "lane_widths": abs(c.delta_u)}
        for c in scene.target_lane_changes
    ]
    others = [
        {"object_id": h.object_id, "t": h.onset_t, "reason": h.reason} for h in scene.hazards if h.object_id != target
    ]
    timeline = [{"t": h.onset_t, "event": f"vehicle {h.object_id} became a hazard ({h.reason})"} for h in scene.hazards]
    timeline += [
        {"t": c["start_t"], "event": f"struck vehicle starts moving {c['direction']} across the lane"} for c in changes
    ]
    timeline.append({"t": impact_t, "event": "impact"})
    geometry = _geometry(tracks, clip, target)
    timeline.sort(key=lambda e: e["t"])
    return {
        "clip_id": clip["clip_id"],
        "impact_t": impact_t,
        "tracked_vehicles": scene.tracked_vehicles,
        "struck_vehicle": target,
        "struck_vehicle_geometry": geometry,
        "hazard_onset": onset,
        "struck_vehicle_lane_changes": changes,
        "other_hazards": others,
        "conditions": scene.conditions,
        "timeline": timeline,
        "summary": _summary(scene.tracked_vehicles, target, onset, changes, others, scene.conditions, impact_t)
        + ([CROSSING] if geometry == "side_or_crossing" else []),
        "attribution": ATTRIBUTION,
    }


def _geometry(tracks: dict, clip: dict, target: str | None) -> str | None:
    """Whether the struck vehicle was ahead in our lane before impact, or came from the side or across our path."""
    if target is None:
        return None
    impact_frame = round(clip["time_of_event"] * tracks["fps"])
    dets = sorted(tracks["objects"][target], key=lambda d: d["frame"])
    first = impact_frame - round(TARGET_WINDOW_S * tracks["fps"])
    overlap = mean_lane_overlap(dets, lane_polygon_px(tracks, clip), first, impact_frame)
    return "ahead_in_lane" if overlap >= TARGET_MIN_LANE_OVERLAP else "side_or_crossing"


def _summary(
    tracked: int,
    target: str | None,
    onset: dict | None,
    changes: list[dict],
    others: list[dict],
    conditions: dict,
    impact_t: float,
) -> list[str]:
    """Plain-English sentences. Every number comes from the scene; nothing is inferred or invented."""
    sentences = [f"SAM 3.1 tracked {tracked} vehicles."]
    if target is not None and onset is not None:
        sentences.append(
            f"The struck vehicle (object {target}) became a hazard at {onset['t']:.2f} s ({onset['how']}), "
            f"{onset['warning_s']:.2f} s before the impact at {impact_t:.2f} s."
        )
    elif target is not None:
        sentences.append(
            f"The struck vehicle (object {target}) never registered as a hazard before the impact at {impact_t:.2f} s."
        )
    sentences += [
        f"It moved {c['direction']} across {c['lane_widths']:.2f} lane widths between "
        f"{c['start_t']:.2f} s and {c['end_t']:.2f} s."
        for c in changes
    ]
    if others:
        sentences.append(f"{len(others)} other vehicle(s) also registered as hazards.")
    seen = [f"{label} {conditions[key]}" for key, label in CONDITION_LABELS if key in conditions]
    if seen:
        sentences.append(f"Witness (Muse Spark): {', '.join(seen)}.")
    return sentences


def video_report(clip_id: str) -> dict:
    """Load a clip's cached SAM tracks (and witness answers, if any) and report on it."""
    clip = get_clip(clip_id)
    tracks_path = CACHE / "sam" / f"{clip_id}.json"
    if not tracks_path.exists():
        raise FileNotFoundError(f"no SAM tracks for {clip_id}; run `telltale sam {clip_id}` first")
    witness_path = CACHE / "witness" / f"{clip_id}.json"
    witness = json.loads(witness_path.read_text())["answers"] if witness_path.exists() else None
    return build_video_report(json.loads(tracks_path.read_text()), clip, witness)
