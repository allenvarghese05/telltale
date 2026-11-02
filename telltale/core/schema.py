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
    clip_id: str
    fps: float
    lane_entry_t: float
    impact_t: float
    ttc_at_entry: float | None
    target_object_id: str
