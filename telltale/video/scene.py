"""Everything the video alone can say about an incident, and the few facts worth putting in evidence.

Two different audiences, deliberately kept apart:

`SceneSummary` is rich. It carries every tracked vehicle, every hazard and when it became one, the target's
lane changes, and the witness's conditions. That detail belongs in the video-only report and the replay UI,
where a person reads it.

`scene_facts` is deliberately small. Every fact the agent can see is a fact it may cite, and the checker
blocks any claim it cannot recompute — so decorative evidence does not help an investigation, it just gives
the agent more rope. Only numbers that are deterministically recomputable *and* plausibly causal become
facts; the rest stays in the summary.

Track B's `build_store` takes an `extra_facts` argument, so these reach the evidence store without any
shared file changing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from telltale.core.schema import Fact
from telltale.video.hazard import HazardOnset, hazard_onsets
from telltale.video.lane import select_target
from telltale.video.motion import LaneChange, lane_change_events


@dataclass(frozen=True)
class SceneSummary:
    clip_id: str
    tracked_vehicles: int
    hazards: list[HazardOnset]
    target_object_id: str | None
    target_lane_changes: list[LaneChange]
    danger_onset_t: float | None
    danger_onset_reason: str | None
    first_hazard_t: float | None
    conditions: dict = field(default_factory=dict)


def summarize_scene(tracks: dict, clip: dict, witness_answers: dict | None = None) -> SceneSummary:
    hazards = hazard_onsets(tracks, clip)
    poly = [(x * tracks["width"], y * tracks["height"]) for x, y in clip["ego_lane_polygon"]]
    try:
        target = select_target(tracks["objects"], round(clip["time_of_event"] * tracks["fps"]))
    except ValueError:
        target = None
    changes: list[LaneChange] = []
    if target is not None:
        dets = sorted(tracks["objects"][target], key=lambda d: d["frame"])
        changes = lane_change_events(dets, tracks["fps"], poly)
    # Danger onset is the *struck* vehicle's, not the scene's earliest. Perception latency asks when the
    # system could have known about the threat it failed to avoid; a different car becoming briefly
    # interesting earlier is context, not the incident. Scene-wide onsets ran 0.2-1.4s ahead of Nexar's
    # human alert label on the demo clips, which is the symptom of answering the wrong question.
    of_target = next((h for h in hazards if h.object_id == target), None)
    return SceneSummary(
        clip_id=clip["clip_id"],
        tracked_vehicles=len(tracks["objects"]),
        hazards=hazards,
        target_object_id=target,
        target_lane_changes=changes,
        danger_onset_t=of_target.onset_t if of_target else None,
        danger_onset_reason=of_target.reason if of_target else None,
        first_hazard_t=hazards[0].onset_t if hazards else None,
        conditions=dict(witness_answers or {}),
    )


def scene_facts(scene: SceneSummary) -> list[Fact]:
    """The curated subset that belongs in the evidence store, for `build_store(extra_facts=...)`.

    The struck vehicle's hazard onset is not repeated here: it is core evidence (`VID:hazard_onset_t`), written
    by the evidence builder from `VideoFacts`.
    """
    return [
        Fact(
            "VID:hazard_vehicle_count",
            len(scene.hazards),
            "",
            "VID",
            "tracked vehicles that entered the ego lane, were predicted to, or closed within it",
        ),
        Fact(
            "VID:target_lane_changes",
            len(scene.target_lane_changes),
            "",
            "VID",
            "sustained lateral manoeuvres by the struck vehicle, in lane widths per second",
        ),
    ]
