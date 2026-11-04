"""Plain-English titles for the site's investigation chooser, built only from fields a bundle already has.

No numbers and no model text: the crash is described from the scene (how the struck vehicle became a hazard, and the
witness's lighting and weather) and the outcome from the checker's own verdict label.
"""

from __future__ import annotations

CRASH_KIND = {
    "closing": "Rear-end crash",
    "entering": "Lane cut-in",
    "predicted": "Lane cut-in",
    "collision_course": "Side or crossing crash",
}

VEHICLE = {"car": "Car", "truck": "Loaded truck"}

OUTCOME = {
    "PERCEPTION_LATE": "noticed the hazard too late",
    "COMMAND_LATE": "noticed in time, braked too late",
    "BRAKE_ACTUATION_LATE": "brakes slow to engage",
    "LATE_HANDOFF": "handed back to the driver too late",
    "UNAVOIDABLE": "unavoidable, even with a perfect response",
    "NO_FAULT_FOUND": "avoidable, but no step was over its limit",
    "INCONCLUSIVE": "inconclusive, the logs are incomplete",
}

RED_TEAM = "Someone edits the AI's answer: the checker catches it"
UNKNOWN = {"", "unclear", "unknown", "none"}


def crash_title(bundle: dict) -> str:
    """e.g. "Rear-end crash on an overcast day", "Lane cut-in at night"."""
    scene = bundle.get("scene") or {}
    conditions = scene.get("conditions") or {}
    kind = CRASH_KIND.get(scene.get("danger_onset_reason"), "Crash")
    lighting = str(conditions.get("lighting") or "").strip().lower()
    weather = str(conditions.get("weather") or "").strip().lower()
    if lighting == "night":
        return f"{kind} at night"
    if lighting == "daylight" and weather not in UNKNOWN:
        article = "an" if weather[0] in "aeiou" else "a"
        return f"{kind} on {article} {weather} day"
    if lighting == "daylight":
        return f"{kind} in daylight"
    return kind


def investigation_title(bundle: dict) -> str:
    """e.g. "Car: noticed the hazard too late", "Loaded truck: brakes slow to engage"."""
    verdict = bundle.get("verdict") or {}
    if bundle.get("red_team"):
        return RED_TEAM
    vehicle = VEHICLE.get(bundle.get("profile"), "Vehicle")
    if verdict.get("status") != "VERIFIED":
        return f"{vehicle}: the AI and the checker disagree"
    return f"{vehicle}: {OUTCOME.get(verdict.get('independent_label'), 'no verdict')}"


def pick_default(entries: list[dict]) -> str:
    """Open on a complete, unaltered story: the first crash's car case where the hazard was noticed too late."""
    first_clip = min(entry["clip_id"] for entry in entries)
    for entry in entries:
        if (
            entry["clip_id"] == first_clip
            and entry["profile"] == "car"
            and entry["label"] == "PERCEPTION_LATE"
            and not entry["red_team"]
        ):
            return entry["case_id"]
    return entries[0]["case_id"]
