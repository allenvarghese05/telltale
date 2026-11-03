"""Shared value types. These are locked contracts between tracks; change them only on main."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["VERIFIED", "UNCORROBORATED", "BLOCKED"]
ClaimType = Literal["timing", "physics", "observation", "attribution", "other"]
LABELS = (
    "PERCEPTION_LATE",
    "COMMAND_LATE",
    "BRAKE_ACTUATION_LATE",
    "LATE_HANDOFF",
    "UNAVOIDABLE",
    "NO_FAULT_FOUND",
    "INCONCLUSIVE",
)
HIDDEN_FROM_AGENT = ("PHYS:", "ATTR:")
HAZARD_REASONS = {
    "entering": "struck vehicle crossed laterally into the ego lane (SAM 3.1 box)",
    "predicted": "struck vehicle outside the ego lane, closing on its edge within 2 s at the measured rate",
    "closing": "struck vehicle already in the ego lane with time-to-collision under 2 s",
}


@dataclass(frozen=True)
class Fact:
    """One piece of evidence. `id` is `<SOURCE>:<name>`; times are video seconds."""

    id: str
    value: float | int | str | bool
    unit: str
    source: str
    derivation: str
    kind: str = "measurement"  # measurement | observation | derived


@dataclass
class Claim:
    text: str
    type: ClaimType
    evidence: list[str]
    assertion: dict | None = None


@dataclass
class CheckResult:
    claim: Claim
    status: Status
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VideoFacts:
    """What the footage alone establishes. `hazard_onset_t` is the physics time origin for every case.

    The struck vehicle becomes a hazard by `entering` the ego lane, being `predicted` to cross into it within
    2 s, or `closing` inside it with time-to-collision under 2 s (a rear-end). Lane entry is one kind of onset.
    """

    clip_id: str
    fps: float
    hazard_onset_t: float
    hazard_onset_reason: str
    impact_t: float
    ttc_at_onset: float | None
    target_object_id: str
