"""Generate the demo cases: one real clip, several vehicle logs, so the same footage gets different verdicts."""

from __future__ import annotations

import json
import zlib

from telltale.config import CACHE, CASES, GROUND_TRUTH
from telltale.core.manifest import get_clip, load_manifest
from telltale.logs.generate import ClipTiming, GenerationError, generate_case
from telltale.physics.profiles import PROFILES
from telltale.video.facts import compute_video_facts

# The UI labels a clip's logs in case-id order, i.e. car before truck, then seed order within each profile.
DEMO_STORIES = ("perception_late", "command_late", "brake_slow", "late_handoff", "unavoidable")
DEMO = [(profile, story) for profile in ("car", "truck") for story in DEMO_STORIES]
TRUCK_SEED_OFFSET = 500


def demo_seed(clip_id: str, story: str, profile: str = "car") -> int:
    """A seed that differs per clip but keeps the stories in the same A..E order on every clip.

    One shared seed per story gave every clip the same hidden parameters, so cand36 and cand38 both showed a
    1.36 s perception latency. Story k gets seeds k000-k999, offset by a stable hash of the clip id (crc32,
    since Python's own string hash changes between runs). Truck cases shift that offset by half the range, so a
    truck never replays the car's draw for the same story.
    """
    story_index = DEMO_STORIES.index(story) + 1
    offset = TRUCK_SEED_OFFSET if profile == "truck" else 0
    return 1000 * story_index + (zlib.crc32(clip_id.encode()) + offset) % 1000


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
        for profile, story in DEMO:
            try:
                made.append(generate_for_clip(clip_id, profile, story, demo_seed(clip_id, story, profile)))
            except GenerationError as exc:
                skipped.append(f"{clip_id}/{story}: {exc}")
    return {"cases": made, "skipped": skipped}
