"""Deterministic fault attribution: the layer whose latency most exceeded its tolerance, if any mattered."""

from __future__ import annotations

from dataclasses import dataclass, field

LAYER_LABEL = {
    "perception": "PERCEPTION_LATE",
    "command": "COMMAND_LATE",
    "actuation": "BRAKE_ACTUATION_LATE",
    "handoff": "LATE_HANDOFF",
}


@dataclass
class Measured:
    perception_latency: float | None
    command_latency: float | None
    actuation_latency: float | None
    handoff_margin: float | None
    cf_nominal_contact: bool | None
    data_complete: bool = True


@dataclass
class Verdict:
    label: str
    excess: dict
    noncausal_faults: list = field(default_factory=list)


def attribute(m: Measured, profile) -> Verdict:
    """Pick the primary cause. Unavoidable physics and incomplete logs both override layer faults."""
    thr = profile.thresholds
    excess: dict[str, float] = {}
    if m.perception_latency is not None:
        excess["perception"] = m.perception_latency - thr["perception_s"]
    if m.command_latency is not None:
        excess["command"] = m.command_latency - thr["command_s"]
    if m.actuation_latency is not None:
        excess["actuation"] = m.actuation_latency - thr["actuation_s"]
    if m.handoff_margin is not None:
        excess["handoff"] = thr["human_prt_s"] - m.handoff_margin
    faults = [k for k, v in excess.items() if v > 0]
    if not m.data_complete or m.cf_nominal_contact is None:
        return Verdict("INCONCLUSIVE", excess)
    if m.cf_nominal_contact:
        return Verdict("UNAVOIDABLE", excess, faults)
    if not faults:
        return Verdict("NO_FAULT_FOUND", excess)
    return Verdict(LAYER_LABEL[max(faults, key=lambda k: excess[k])], excess)
