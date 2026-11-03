"""The deterministic engine: read a case's logs blind, align clocks, derive latencies, run the counterfactual
and attribute the primary cause. Produces the hashed evidence store the agent reads and the checker verifies.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from telltale.core.schema import Fact, VideoFacts
from telltale.evidence.align import align_by_speed, can_offset_from_impact
from telltale.evidence.store import EvidenceStore
from telltale.logs.can_io import decode_signals, load_dbc, read_candump
from telltale.logs.mcap_io import read_adas_mcap
from telltale.physics.attribution import Measured, attribute
from telltale.physics.counterfactual import counterfactual
from telltale.physics.sim import BrakeModel, simulate

PRESSURE_FRAC = 0.6
MAX_BRAKE_GAP_S = 0.1


def _first(ts, vs, pred, after: float = -math.inf) -> float | None:
    for t, v in zip(ts, vs, strict=True):
        if t >= after and pred(v):
            return float(t)
    return None


def build_store(case_dir, video: VideoFacts, profile, extra_facts: list[Fact] | None = None) -> EvidenceStore:
    """Build the evidence store for one case. `video` is the only thing known from the footage."""
    case_dir = Path(case_dir)
    sig = decode_signals(read_candump(case_dir / "vehicle.can.log"), load_dbc(profile.dbc))
    impact_ts = _first(*sig["impact"], lambda v: v >= 1)
    if impact_ts is None:
        raise ValueError("CAN log has no EDR impact trigger")
    can_off = can_offset_from_impact(video.impact_t, impact_ts)

    def tv(name):
        t, v = sig[name]
        return np.asarray(t) + can_off, np.asarray(v)

    spd_t, spd_v = tv("speed_mps")
    req_t, req_v = tv("brake_request")
    prs_t, prs_v = tv("brake_pressure_kpa")

    av = read_adas_mcap(case_dir / "adas.mcap")
    av_t = np.array([t for t, _ in av["/ego/speed"]])
    av_v = np.array([m["speed_mps"] for _, m in av["/ego/speed"]])
    av_off = align_by_speed(spd_t, spd_v, av_t, av_v, guess=can_off)
    track_t, track = av["/adas/tracks"][0]
    first_seen = track_t + av_off
    events = {m["event"]: t + av_off for t, m in av.get("/adas/events", [])}

    can_req = _first(req_t, req_v, lambda v: v >= 1)
    reached = (
        None
        if can_req is None
        else _first(prs_t, prs_v, lambda v: v >= PRESSURE_FRAC * profile.p_max_kpa, after=can_req)
    )
    w0, w1 = first_seen, video.impact_t + 0.5
    inside = np.sort(prs_t[(prs_t >= w0) & (prs_t <= w1)])
    max_gap = float(np.max(np.diff(np.concatenate(([w0], inside, [w1])))))
    complete = max_gap <= MAX_BRAKE_GAP_S

    entry = video.lane_entry_t
    handoff = events.get("handoff")
    perception = first_seen - entry
    command = None if handoff is not None or "brake_request" not in events else events["brake_request"] - first_seen
    actuation = None if can_req is None or reached is None else reached - can_req
    margin = None if handoff is None else video.impact_t - handoff

    v0 = float(np.interp(entry, spd_t, spd_v))
    dv = float(track["rel_speed_mps"])
    d0 = float(track["range_m"]) + dv * (first_seen - entry)
    t_end = video.impact_t - entry + 2.0
    cf = counterfactual(v0, v0 - dv, d0, profile, t_end=t_end)
    tau_est = None if actuation is None else max(actuation / math.log(1 / (1 - PRESSURE_FRAC)), 0.01)
    actual_speed = None
    if can_req is not None and tau_est is not None:
        actual_speed = simulate(
            v0, v0 - dv, d0, can_req - entry, BrakeModel(profile.a_max, tau_est), t_end=t_end
        ).impact_rel_speed
    verdict = attribute(Measured(perception, command, actuation, margin, cf.contact, complete), profile)

    facts: list[Fact] = []

    def add(fid, value, unit, src, how, kind="measurement"):
        if value is None:
            return
        if isinstance(value, float):
            value = round(value, 4)
        facts.append(Fact(fid, value, unit, src, how, kind))

    add(
        "VID:lane_entry_t",
        entry,
        "s",
        "VID",
        f"SAM 3.1 object {video.target_object_id} box bottom-centre entered ego-lane polygon",
    )
    add("VID:impact_t", video.impact_t, "s", "VID", "Nexar dataset time_of_event label")
    add("VID:ttc_at_entry_s", video.ttc_at_entry, "s", "VID", "box width / d(width)/dt at lane entry")
    add("VID:target_object_id", video.target_object_id, "", "VID", "largest tracked vehicle at impact frame")
    add("CAN:clock_offset_s", can_off, "s", "CAN", "EDR impact trigger aligned to video impact")
    add("AV:clock_offset_s", av_off, "s", "AV", "ADAS ego-speed trace aligned to CAN speed (MSE grid search)")
    add("AV:first_seen_t", first_seen, "s", "AV", "first /adas/tracks message for the cut-in vehicle")
    add("AV:brake_request_t", events.get("brake_request"), "s", "AV", "/adas/events brake_request")
    add("AV:handoff_t", handoff, "s", "AV", "/adas/events handoff to driver")
    add("AV:range_at_first_seen_m", float(track["range_m"]), "m", "AV", "radar range at first detection")
    add("AV:rel_speed_mps", dv, "m/s", "AV", "radar closing speed at first detection")
    add("CAN:brake_request_t", can_req, "s", "CAN", "first brake_request=1 frame")
    add(
        "CAN:pressure_reached_t",
        reached,
        "s",
        "CAN",
        f"brake pressure first >= {int(PRESSURE_FRAC * 100)}% of full application",
    )
    add("CAN:speed_at_entry_mps", v0, "m/s", "CAN", "CAN wheel speed interpolated at lane entry")
    add("PHYS:perception_latency_s", perception, "s", "PHYS", "AV:first_seen_t - VID:lane_entry_t", "derived")
    add("PHYS:command_latency_s", command, "s", "PHYS", "AV:brake_request_t - AV:first_seen_t", "derived")
    add("PHYS:actuation_latency_s", actuation, "s", "PHYS", "CAN:pressure_reached_t - CAN:brake_request_t", "derived")
    add("PHYS:handoff_margin_s", margin, "s", "PHYS", "VID:impact_t - AV:handoff_t", "derived")
    add("PHYS:brake_tau_est_s", tau_est, "s", "PHYS", "first-order time constant from actuation latency", "derived")
    add("PHYS:gap_at_entry_m", d0, "m", "PHYS", "radar range back-propagated to lane entry", "derived")
    add("PHYS:actual_impact_speed_mps", actual_speed, "m/s", "PHYS", "replay with measured timings", "derived")
    add(
        "PHYS:cf_nominal_contact",
        bool(cf.contact),
        "",
        "PHYS",
        "counterfactual with nominal perception/command/actuation",
        "derived",
    )
    add("PHYS:cf_nominal_min_gap_m", cf.min_gap, "m", "PHYS", "counterfactual closest gap", "derived")
    add(
        "PHYS:cf_nominal_impact_speed_mps", cf.impact_rel_speed, "m/s", "PHYS", "counterfactual impact speed", "derived"
    )
    for k, name in (
        ("perception_s", "perception"),
        ("command_s", "command"),
        ("actuation_s", "actuation"),
        ("human_prt_s", "human_prt"),
    ):
        add(
            f"PROFILE:{name}_threshold_s" if name != "human_prt" else "PROFILE:human_prt_s",
            profile.thresholds[k],
            "s",
            "PROFILE",
            f"{profile.name} profile tolerance",
        )
    add(
        "PROFILE:nominal_perception_s",
        profile.nominal["perception_s"],
        "s",
        "PROFILE",
        "nominal value for counterfactuals",
    )
    add("PROFILE:nominal_command_s", profile.nominal["command_s"], "s", "PROFILE", "nominal value for counterfactuals")
    add("PROFILE:nominal_tau_s", profile.tau_nominal, "s", "PROFILE", "nominal brake time constant for counterfactuals")
    add(
        "DATA:brake_log_complete",
        bool(complete),
        "",
        "DATA",
        f"no brake-frame gap > {MAX_BRAKE_GAP_S}s in decision window",
    )
    add("DATA:max_brake_gap_s", max_gap, "s", "DATA", "largest gap between brake frames in decision window")
    for k, v in verdict.excess.items():
        add(f"ATTR:excess_{k}_s", v, "s", "ATTR", f"measured {k} latency minus tolerance", "derived")
    add("ATTR:label", verdict.label, "", "ATTR", "deterministic but-for attribution", "derived")
    add(
        "ATTR:noncausal_faults",
        ",".join(verdict.noncausal_faults) or "none",
        "",
        "ATTR",
        "faults present but not causal",
        "derived",
    )
    facts.extend(extra_facts or [])

    series = {
        "can.speed_mps": {"t": spd_t.tolist(), "v": spd_v.tolist(), "unit": "m/s", "source": "CAN"},
        "can.brake_pressure_kpa": {"t": prs_t.tolist(), "v": prs_v.tolist(), "unit": "kPa", "source": "CAN"},
        "can.brake_request": {"t": req_t.tolist(), "v": req_v.tolist(), "unit": "", "source": "CAN"},
        "av.speed_mps": {"t": (av_t + av_off).tolist(), "v": av_v.tolist(), "unit": "m/s", "source": "AV"},
    }
    return EvidenceStore(facts, series)
