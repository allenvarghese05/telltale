"""Generate the demo cases: one real clip, several vehicle logs, so the same footage gets different verdicts."""

from __future__ import annotations

import json

from telltale.config import CACHE, CASES, GROUND_TRUTH
from telltale.core.manifest import get_clip, load_manifest
from telltale.logs.generate import ClipTiming, GenerationError, generate_case
from telltale.physics.profiles import PROFILES
from telltale.video.facts import compute_video_facts

# UI buttons "Vehicle log A..E" follow seed order. The truck profile is exercised in the benchmarks.
DEMO = [
    ("car", "perception_late", 101),
    ("car", "command_late", 102),
    ("car", "brake_slow", 103),
    ("car", "late_handoff", 104),
    ("car", "unavoidable", 105),
]


def clip_timing(clip_id: str) -> ClipTiming:
    """The physics time origin (hazard onset) and impact time measured from a clip's footage."""
    tracks = json.loads((CACHE / "sam" / f"{clip_id}.json").read_text())
    video = compute_video_facts(tracks, get_clip(clip_id))
    return ClipTiming(clip_id, video.hazard_onset_t, video.impact_t)


def generate_for_clip(clip_id: str, profile: str, story: str, seed: int) -> str:
    return generate_case(clip_timing(clip_id), PROFILES[profile], story, seed, CASES, GROUND_TRUTH)


def make_demo() -> dict:
    """Generate every demo story for every clip in the manifest; report the ones the footage can't host."""
    made, skipped = [], []
    for clip_id in load_manifest()["clips"]:
        for profile, story, seed in DEMO:
            try:
                made.append(generate_for_clip(clip_id, profile, story, seed))
            except GenerationError as exc:
                skipped.append(f"{clip_id}/{story}: {exc}")
    return {"cases": made, "skipped": skipped}
