"""A plain-English incident report, written by deterministic code from a case bundle.

The pitch is that nothing reaches the reader unchecked, so this text is never written by a model. Every number
in it is a value already in the bundle, formatted and nothing more, and every sentence carries the evidence it
came from: a fact ID, or a `scene.` / `verdict.` / `counts` path for the parts of the bundle that are not facts.
A missing field drops its sentence. Nothing is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

HAZARD_HOW = {
    "entering": "it moved into the camera car's lane",
    "predicted": "it was about to move into the camera car's lane",
    "closing": "it was already in the camera car's lane, and the gap was closing",
}

CONCLUSION = {
    "PERCEPTION_LATE": "the car's driver-assist noticed the hazard too late",
    "COMMAND_LATE": "the car's driver-assist noticed the hazard in time but commanded the brakes too late",
    "BRAKE_ACTUATION_LATE": "the brakes engaged too slowly",
    "LATE_HANDOFF": "the car's driver-assist handed control to the driver too late for a person to react",
    "UNAVOIDABLE": "the collision could not have been avoided even with normal timing",
    "NO_FAULT_FOUND": "the collision was avoidable, but no step exceeded its limit",
    "INCONCLUSIVE": "the evidence is not complete enough to decide",
}

STEP = {
    "perception": "noticing the vehicle",
    "command": "commanding the brakes",
    "actuation": "engaging the brakes",
    "handoff": "handing control to the driver",
}

UNKNOWN = {"", "unclear", "unknown", "none"}


@dataclass(frozen=True)
class Sentence:
    text: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class Section:
    title: str
    sentences: tuple[Sentence, ...]


def _s(t: float) -> str:
    return f"{float(t):.2f}"


def _kmh(mps: float) -> str:
    return f"{float(mps) * 3.6:.1f}"


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


def _camera(facts: dict, scene: dict) -> list[Sentence]:
    out = []
    if scene.get("tracked_vehicles"):
        n = scene["tracked_vehicles"]
        out.append(
            Sentence(
                f"Automatic tracking followed {_count(n, 'vehicle', 'vehicles')} in the dashcam footage.",
                ("scene.tracked_vehicles",),
            )
        )
    if "VID:hazard_onset_t" in facts:
        how = HAZARD_HOW.get(facts.get("VID:hazard_onset_reason"))
        when = f"At {_s(facts['VID:hazard_onset_t'])} seconds, the other vehicle became a hazard"
        out.append(
            Sentence(f"{when}: {how}.", ("VID:hazard_onset_t", "VID:hazard_onset_reason"))
            if how
            else Sentence(f"{when}.", ("VID:hazard_onset_t",))
        )
    for change in scene.get("target_lane_changes") or []:
        out.append(
            Sentence(
                f"Between {_s(change['start_t'])} and {_s(change['end_t'])} seconds, "
                f"it changed lanes to the {change['direction']}.",
                ("scene.target_lane_changes",),
            )
        )
    seen = [
        (fid, text)
        for fid, text in (
            ("WIT:lighting", facts.get("WIT:lighting")),
            ("WIT:weather", facts.get("WIT:weather")),
            ("WIT:road_surface", f"a {facts['WIT:road_surface']} road" if "WIT:road_surface" in facts else None),
        )
        if text and str(facts[fid]).strip().lower() not in UNKNOWN
    ]
    if seen:
        out.append(
            Sentence(
                "A second model watching the same footage described the conditions as "
                f"{_and([str(text) for _, text in seen])}.",
                tuple(fid for fid, _ in seen),
            )
        )
    return out


def _systems(facts: dict) -> list[Sentence]:
    out = []
    if "AV:first_seen_t" in facts:
        out.append(
            Sentence(
                f"At {_s(facts['AV:first_seen_t'])} seconds, the car's driver-assist first noticed the vehicle.",
                ("AV:first_seen_t",),
            )
        )
    if "AV:handoff_t" in facts:
        out.append(
            Sentence(
                f"At {_s(facts['AV:handoff_t'])} seconds, the car's driver-assist handed control back to the driver.",
                ("AV:handoff_t",),
            )
        )
    elif "AV:brake_request_t" in facts:
        out.append(
            Sentence(f"At {_s(facts['AV:brake_request_t'])} seconds, it commanded the brakes.", ("AV:brake_request_t",))
        )
    if "CAN:pressure_reached_t" in facts:
        out.append(
            Sentence(
                f"At {_s(facts['CAN:pressure_reached_t'])} seconds, the brakes engaged.", ("CAN:pressure_reached_t",)
            )
        )
    if "VID:impact_t" in facts:
        out.append(Sentence(f"The collision happened at {_s(facts['VID:impact_t'])} seconds.", ("VID:impact_t",)))
    return out


def _interval(facts: dict, measured: str, limit: str, said: str, allowed: str) -> list[Sentence]:
    out = []
    if measured in facts:
        out.append(Sentence(said.format(_s(facts[measured])), (measured,)))
        if limit in facts:
            out.append(Sentence(allowed.format(_s(facts[limit])), (limit,)))
    return out


def _chain(facts: dict) -> list[Sentence]:
    out = []
    if facts.get("DATA:brake_log_complete") is False and "DATA:max_brake_gap_s" in facts:
        out.append(
            Sentence(
                f"The brake log is incomplete: it is missing {_s(facts['DATA:max_brake_gap_s'])} seconds of data "
                "while braking was being decided, so brake timing cannot be measured reliably.",
                ("DATA:brake_log_complete", "DATA:max_brake_gap_s"),
            )
        )
    out += _interval(
        facts,
        "PHYS:perception_latency_s",
        "PROFILE:perception_threshold_s",
        "The car's driver-assist took {} seconds to notice the vehicle.",
        "A driver-assist performing to specification would notice within {} seconds.",
    )
    out += _interval(
        facts,
        "PHYS:command_latency_s",
        "PROFILE:command_threshold_s",
        "It then took {} seconds to command the brakes.",
        "The specification allows {} seconds.",
    )
    out += _interval(
        facts,
        "PHYS:actuation_latency_s",
        "PROFILE:actuation_threshold_s",
        "The brakes took {} seconds to engage once commanded.",
        "The specification allows {} seconds.",
    )
    out += _interval(
        facts,
        "PHYS:handoff_margin_s",
        "PROFILE:human_prt_s",
        "The driver then had {} seconds before the collision.",
        "A person typically needs {} seconds to react.",
    )
    excess = {fid: float(v) for fid, v in facts.items() if fid.startswith("ATTR:excess_")}
    if excess:
        worst = max(excess, key=excess.__getitem__)
        layer = worst.removeprefix("ATTR:excess_").removesuffix("_s")
        if excess[worst] > 0 and layer in STEP:
            out.append(
                Sentence(
                    f"The largest overrun was in {STEP[layer]}: {_s(excess[worst])} seconds past its limit.",
                    (worst,),
                )
            )
        elif excess[worst] <= 0:
            out.append(Sentence("Every step stayed within its limit.", tuple(sorted(excess))))
    return out


def _but_for(facts: dict) -> list[Sentence]:
    out = []
    if "PHYS:actual_impact_speed_mps" in facts:
        out.append(
            Sentence(
                "As it happened, the vehicles collided at a closing speed of "
                f"{_kmh(facts['PHYS:actual_impact_speed_mps'])} km/h.",
                ("PHYS:actual_impact_speed_mps",),
            )
        )
    contact = facts.get("PHYS:cf_nominal_contact")
    replay = "Replayed with every step performing to specification, the collision"
    if contact is False:
        out.append(Sentence(f"{replay} is avoided.", ("PHYS:cf_nominal_contact",)))
        if "PHYS:cf_nominal_min_gap_m" in facts:
            out.append(
                Sentence(
                    f"The vehicles come no closer than {_s(facts['PHYS:cf_nominal_min_gap_m'])} metres.",
                    ("PHYS:cf_nominal_min_gap_m",),
                )
            )
    elif contact is True and "PHYS:cf_nominal_impact_speed_mps" in facts:
        speed = _kmh(facts["PHYS:cf_nominal_impact_speed_mps"])
        out.append(
            Sentence(
                f"{replay} still happens, at a closing speed of {speed} km/h.",
                ("PHYS:cf_nominal_contact", "PHYS:cf_nominal_impact_speed_mps"),
            )
        )
    elif contact is True:
        out.append(Sentence(f"{replay} still happens.", ("PHYS:cf_nominal_contact",)))
    return out


def _verification(verdict: dict, counts: dict) -> list[Sentence]:
    out = []
    agent = CONCLUSION.get(verdict.get("agent_label"))
    if agent:
        out.append(Sentence(f"The AI investigator concluded that {agent}.", ("verdict.agent_label",)))
    recomputed = "Separate code, with no AI involved, recomputed the conclusion from the same evidence"
    if verdict.get("status") == "VERIFIED":
        out.append(Sentence(f"{recomputed} and agreed.", ("ATTR:label", "verdict.status")))
    elif verdict.get("status") == "REJECTED" and verdict.get("independent_label") in CONCLUSION:
        out.append(
            Sentence(
                f"{recomputed} and found instead that {CONCLUSION[verdict['independent_label']]}.",
                ("ATTR:label",),
            )
        )
        out.append(
            Sentence(
                "Because the two disagree, this conclusion is withheld until a human reviewer decides.",
                ("verdict.status",),
            )
        )
    if counts:
        ok, single, blocked = (int(counts.get(k, 0)) for k in ("VERIFIED", "UNCORROBORATED", "BLOCKED"))
        out.append(
            Sentence(
                f"Of the investigator's {_count(ok + single + blocked, 'claim', 'claims')}, "
                f"{ok} {'was' if ok == 1 else 'were'} confirmed by recomputation, "
                f"{single} {'rests' if single == 1 else 'rest'} on a single source "
                f"and {blocked} {'was' if blocked == 1 else 'were'} blocked.",
                ("counts",),
            )
        )
    return out


LIMITS = (
    Sentence("This report identifies which step in the vehicle's response fell outside its specification.", ()),
    Sentence("It does not decide who is legally responsible for the collision.", ()),
    Sentence("A qualified human reviewer signs off before it is relied on.", ()),
    Sentence("The vehicle logs in this demo are generated, because real fleet driver-assist logs are proprietary.", ()),
    Sentence("Given a real fleet's logs, the same pipeline runs unchanged.", ()),
)


def incident_report(bundle: dict) -> list[Section]:
    """The six sections of the plain-English report, in reading order, leaving out any that have nothing to say."""
    facts = {f["id"]: f["value"] for f in bundle.get("facts", [])}
    sections = [
        ("What the camera saw", _camera(facts, bundle.get("scene") or {})),
        ("What the vehicle's systems did", _systems(facts)),
        ("Where the chain broke", _chain(facts)),
        ("Would normal timing have avoided it?", _but_for(facts)),
        ("How this was verified", _verification(bundle.get("verdict") or {}, bundle.get("counts") or {})),
        ("What this report does not say", list(LIMITS)),
    ]
    return [Section(title, tuple(lines)) for title, lines in sections if lines]
