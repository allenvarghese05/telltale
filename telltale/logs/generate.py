"""Blind fault-injecting case generator.

Time zero is the video's hazard-onset moment. The gap at hazard onset is solved so simulated contact lands on the
video's impact time, so every generated log agrees with the footage. Injected faults only change what video
cannot see: when the system perceived, when it commanded, and how fast brake pressure built.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from telltale.logs.can_io import load_dbc, message_for_signal, write_candump
from telltale.logs.mcap_io import write_adas_mcap
from telltale.physics.attribution import Measured, attribute
from telltale.physics.counterfactual import counterfactual
from telltale.physics.sim import BrakeModel, pressure_reached_time, simulate

EPOCH0 = 1_700_000_000.0
CAN_HZ, AV_HZ = 50.0, 20.0
LOG_TAIL_S = 2.0
POST_IMPACT_DECEL = 12.0
EXPECTED = {
    "unavoidable": "UNAVOIDABLE",
    "perception_late": "PERCEPTION_LATE",
    "command_late": "COMMAND_LATE",
    "brake_slow": "BRAKE_ACTUATION_LATE",
    "late_handoff": "LATE_HANDOFF",
    "dropout": "INCONCLUSIVE",
}
STORIES = tuple(EXPECTED)
# Hard stories for the agent benchmark: the label is decided by small margins, a near miss, or a fault that did not
# matter. The intended label is only accepted when deterministic attribution of the drawn truth reaches it.
HARD_EXPECTED = {
    "tight_perception_command": "PERCEPTION_LATE",
    "tight_command_perception": "COMMAND_LATE",
    "tight_actuation_perception": "BRAKE_ACTUATION_LATE",
    "tight_perception_actuation": "PERCEPTION_LATE",
    "tight_handoff_perception": "LATE_HANDOFF",
    "marginal_perception": "PERCEPTION_LATE",
    "marginal_command": "COMMAND_LATE",
    "marginal_actuation": "BRAKE_ACTUATION_LATE",
    "unavoidable_with_fault": "UNAVOIDABLE",
}
HARD_STORIES = tuple(HARD_EXPECTED)
TIGHT_PRIMARY_EXCESS_S = (0.10, 0.45)
TIGHT_WIN_MARGIN_S = (0.03, 0.09)
MARGINAL_EXCESS_S = (0.01, 0.10)
MARGINAL_ACTUATION_EXCESS_S = (0.03, 0.10)  # CAN pressure frames are 20 ms apart, so stay clear of quantization
NEAR_MISS_EXCESS_S = (-0.04, -0.005)
NONCAUSAL_EXCESS_S = (0.05, 0.40)
HARD_CAN_SKEW_S = 8.0
HARD_AV_REL_SKEW_S = 1.3  # the ADAS aligner searches +/-1.5 s around the CAN offset
PRESSURE_LN = math.log(1.0 / (1.0 - 0.6))


class GenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClipTiming:
    clip_id: str
    hazard_onset_t: float
    impact_t: float


@dataclass
class Truth:
    story: str
    profile: str
    v_ego0: float
    v_other: float
    d0: float
    first_seen: float  # s after hazard onset
    brake_request: float  # s after hazard onset (ADAS, or driver for handoff)
    handoff: float | None  # s after hazard onset
    tau: float
    contact_t: float
    can_skew: float
    av_skew: float
    label: str = ""


def solve_d0(v_ego0: float, v_other: float, t_req: float, brake: BrakeModel, t_imp: float) -> float:
    """Bisect the hazard-onset gap so that simulated contact happens at t_imp seconds after hazard onset."""

    def ct(d0: float) -> float:
        r = simulate(v_ego0, v_other, d0, t_req, brake, t_end=t_imp + 2.0)
        return r.contact_t if r.contact else math.inf

    lo, hi = 0.05, (v_ego0 - v_other) * t_imp + 0.5
    if ct(lo) > t_imp or ct(hi) < t_imp:
        raise GenerationError("cannot bracket contact time")
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if ct(mid) <= t_imp:
            lo = mid
        else:
            hi = mid
    if abs(ct(lo) - t_imp) > 0.03:
        raise GenerationError("contact time not reachable with these speeds")
    return lo


def truth_label(t: Truth, profile, T: float) -> str:
    """The label attribution should reach from a perfect reading of this truth, used to accept a sample."""
    if t.story == "dropout":
        return "INCONCLUSIVE"
    m = Measured(
        perception_latency=t.first_seen,
        command_latency=None if t.handoff is not None else t.brake_request - t.first_seen,
        actuation_latency=pressure_reached_time(t.brake_request, t.tau) - t.brake_request,
        handoff_margin=None if t.handoff is None else T - t.handoff,
        cf_nominal_contact=counterfactual(t.v_ego0, t.v_other, t.d0, profile, t_end=T + 2.0).contact,
    )
    return attribute(m, profile).label


def _hard_excess(story: str, rng: np.random.Generator) -> dict[str, float]:
    """How far each faulty layer overran its tolerance (negative: a near miss). Unlisted layers stay nominal."""
    kind, _, layers = story.partition("_")
    if kind == "tight":
        primary, secondary = layers.split("_")
        top = float(rng.uniform(*TIGHT_PRIMARY_EXCESS_S))
        return {primary: top, secondary: top - float(rng.uniform(*TIGHT_WIN_MARGIN_S))}
    if kind == "marginal":
        span = MARGINAL_ACTUATION_EXCESS_S if layers == "actuation" else MARGINAL_EXCESS_S
        near = "command" if layers == "perception" else "perception"
        return {layers: float(rng.uniform(*span)), near: float(rng.uniform(*NEAR_MISS_EXCESS_S))}
    layer = ("perception", "command", "actuation")[int(rng.integers(3))]
    return {layer: float(rng.uniform(*NONCAUSAL_EXCESS_S))}


def _draw_hard(story: str, profile, T: float, rng: np.random.Generator) -> tuple[float, float, float | None, float]:
    """(first_seen, brake_request, handoff, tau) for a hard story, from per-layer excesses over the tolerances."""
    thr = profile.thresholds
    excess = _hard_excess(story, rng)
    first_seen = float(rng.uniform(0.10, 0.25))
    command = float(rng.uniform(0.03, 0.08))
    tau = profile.tau_nominal * float(rng.uniform(0.9, 1.1))
    if "perception" in excess:
        first_seen = thr["perception_s"] + excess["perception"]
    if "command" in excess:
        command = thr["command_s"] + excess["command"]
    if "actuation" in excess:
        tau = (thr["actuation_s"] + excess["actuation"]) / PRESSURE_LN
    if "handoff" not in excess:
        return first_seen, first_seen + command, None, tau
    handoff = T - (thr["human_prt_s"] - excess["handoff"])
    return first_seen, handoff + float(rng.uniform(1.2, 1.6)), handoff, tau


def sample_truth(timing: ClipTiming, profile, story: str, rng: np.random.Generator, max_attempts: int = 400) -> Truth:
    """Draw randomized hidden parameters until the story's expected label is the one attribution would reach."""
    if story in HARD_EXPECTED:
        return _sample_hard_truth(timing, profile, story, rng)
    if story not in EXPECTED:
        raise ValueError(story)
    T = timing.impact_t - timing.hazard_onset_t
    if T <= 0.3:
        raise GenerationError("impact too soon after hazard onset")
    for _ in range(max_attempts):
        v_ego0 = float(rng.uniform(18.0, 30.0))
        dv = float(rng.uniform(3.0, min(16.0, v_ego0 - 2.0)))
        slow = story == "brake_slow"
        tau = profile.tau_nominal * float(rng.uniform(3.5, 5.0) if slow else rng.uniform(0.9, 1.1))
        first_seen = float(rng.uniform(1.0, 1.6) if story == "perception_late" else rng.uniform(0.10, 0.25))
        if first_seen >= T - 0.1:
            continue
        handoff = None
        if story == "late_handoff":
            handoff = T - float(rng.uniform(0.5, 1.1))
            if handoff <= first_seen + 0.05:
                continue
            t_req = handoff + float(rng.uniform(1.2, 1.6))  # human perception-reaction after handoff
        elif story == "command_late":
            t_req = first_seen + float(rng.uniform(0.6, 1.2))  # saw it in time; planner hesitated
        else:
            t_req = first_seen + float(rng.uniform(0.03, 0.08))
        brake = BrakeModel(profile.a_max, tau)
        try:
            d0 = solve_d0(v_ego0, v_ego0 - dv, t_req, brake, T)
        except GenerationError:
            continue
        contact = simulate(v_ego0, v_ego0 - dv, d0, t_req, brake, t_end=T + 2.0).contact_t
        truth = Truth(
            story,
            profile.name,
            v_ego0,
            v_ego0 - dv,
            d0,
            first_seen,
            t_req,
            handoff,
            tau,
            float(contact),
            float(rng.uniform(-0.5, 0.5)),
            float(rng.uniform(-0.8, 0.8)),
        )
        truth.label = truth_label(truth, profile, T)
        if truth.label == EXPECTED[story]:
            return truth
    raise GenerationError(f"no {story} parameters found for {timing}")


def _sample_hard_truth(
    timing: ClipTiming, profile, story: str, rng: np.random.Generator, max_attempts: int = 3000
) -> Truth:
    """Like `sample_truth`, for the hard stories, with larger clock skews on both logs."""
    T = timing.impact_t - timing.hazard_onset_t
    if T <= 0.3:
        raise GenerationError("impact too soon after hazard onset")
    for _ in range(max_attempts):
        v_ego0 = float(rng.uniform(18.0, 30.0))
        dv = float(rng.uniform(3.0, min(16.0, v_ego0 - 2.0)))
        first_seen, t_req, handoff, tau = _draw_hard(story, profile, T, rng)
        if first_seen >= T - 0.1 or (handoff is not None and handoff <= first_seen + 0.05):
            continue
        brake = BrakeModel(profile.a_max, tau)
        try:
            d0 = solve_d0(v_ego0, v_ego0 - dv, t_req, brake, T)
        except GenerationError:
            continue
        contact = simulate(v_ego0, v_ego0 - dv, d0, t_req, brake, t_end=T + 2.0).contact_t
        can_skew = float(rng.uniform(-HARD_CAN_SKEW_S, HARD_CAN_SKEW_S))
        av_skew = can_skew + float(rng.uniform(-HARD_AV_REL_SKEW_S, HARD_AV_REL_SKEW_S))
        truth = Truth(
            story,
            profile.name,
            v_ego0,
            v_ego0 - dv,
            d0,
            first_seen,
            t_req,
            handoff,
            tau,
            float(contact),
            can_skew,
            av_skew,
        )
        truth.label = truth_label(truth, profile, T)
        if truth.label == HARD_EXPECTED[story]:
            return truth
    raise GenerationError(f"no {story} parameters found for {timing}")


def _speed(rel: np.ndarray, sim, v0: float) -> np.ndarray:
    """Ego speed at times `rel` (seconds after hazard onset): cruise, then the simulated brake, then crash decel."""
    tc, vc = sim.contact_t, float(sim.v_ego[-1])
    out = np.empty_like(rel)
    for i, r in enumerate(rel):
        if r < 0:
            out[i] = v0
        elif r <= tc:
            out[i] = float(np.interp(r, sim.t, sim.v_ego))
        else:
            out[i] = max(vc - POST_IMPACT_DECEL * (r - tc), 0.0)
    return out


def _ns(tv: float, skew: float) -> int:
    return round((EPOCH0 + tv + skew) * 1e9)


def write_case(case_dir: Path, timing: ClipTiming, truth: Truth, profile) -> None:
    """Write the CAN and ADAS logs for one case, each on its own skewed clock."""
    case_dir.mkdir(parents=True, exist_ok=True)
    onset = timing.hazard_onset_t
    sim = simulate(
        truth.v_ego0,
        truth.v_other,
        truth.d0,
        truth.brake_request,
        BrakeModel(profile.a_max, truth.tau),
        t_end=timing.impact_t - onset + LOG_TAIL_S,
    )
    t_end = timing.impact_t + LOG_TAIL_S

    tv = np.arange(0.0, t_end, 1.0 / CAN_HZ)
    rel = tv - onset
    speed = _speed(rel, sim, truth.v_ego0)
    since = np.clip(rel - truth.brake_request, 0.0, None)
    pressure = np.where(rel >= truth.brake_request, profile.p_max_kpa * (1.0 - np.exp(-since / truth.tau)), 0.0)
    req = (rel >= truth.brake_request).astype(int)

    db = load_dbc(profile.dbc)
    ms, mb, me = (message_for_signal(db, s) for s in ("speed_mps", "brake_request", "impact"))
    drop = (truth.brake_request - 0.2, truth.brake_request + 1.0) if truth.story == "dropout" else None
    frames = []
    for t_v, r, v, q, p in zip(tv, rel, speed, req, pressure, strict=True):
        ts = EPOCH0 + t_v + truth.can_skew
        frames.append((ts, ms.frame_id, ms.encode({"speed_mps": round(float(v), 2)}), ms.is_extended_frame))
        if drop and drop[0] <= r <= drop[1]:
            continue
        frames.append(
            (
                ts + 0.001,
                mb.frame_id,
                mb.encode({"brake_request": int(q), "brake_pressure_kpa": round(float(p))}),
                mb.is_extended_frame,
            )
        )
    frames.append(
        (EPOCH0 + onset + truth.contact_t + truth.can_skew, me.frame_id, me.encode({"impact": 1}), me.is_extended_frame)
    )
    write_candump(case_dir / "vehicle.can.log", frames)

    msgs = []
    av_tv = np.arange(0.0, t_end, 1.0 / AV_HZ)
    for t_v, v in zip(av_tv, _speed(av_tv - onset, sim, truth.v_ego0), strict=True):
        msgs.append(("/ego/speed", _ns(float(t_v), truth.av_skew), {"speed_mps": round(float(v), 3)}))
    dv = truth.v_ego0 - truth.v_other
    msgs.append(
        (
            "/adas/tracks",
            _ns(onset + truth.first_seen, truth.av_skew),
            {
                "track_id": 7,
                "event": "first_seen",
                "range_m": round(truth.d0 - dv * truth.first_seen, 3),
                "rel_speed_mps": round(dv, 3),
            },
        )
    )
    if truth.handoff is None:
        msgs.append(("/adas/events", _ns(onset + truth.brake_request, truth.av_skew), {"event": "brake_request"}))
    else:
        msgs.append(("/adas/events", _ns(onset + truth.handoff, truth.av_skew), {"event": "handoff"}))
    write_adas_mcap(case_dir / "adas.mcap", msgs)


def generate_case(timing: ClipTiming, profile, story: str, seed: int, out_root, gt_root) -> str:
    """Seeds must be unique per (clip, profile): the case id contains only the seed, never the story."""
    truth = sample_truth(timing, profile, story, np.random.default_rng(seed))
    case_id = f"{timing.clip_id}-{profile.name}-s{seed:04d}"
    case_dir = Path(out_root) / case_id
    write_case(case_dir, timing, truth, profile)
    (case_dir / "case.json").write_text(
        json.dumps({"case_id": case_id, "clip_id": timing.clip_id, "profile": profile.name})
    )
    gt = Path(gt_root)
    gt.mkdir(parents=True, exist_ok=True)
    (gt / f"{case_id}.json").write_text(json.dumps({**asdict(truth), "expected_label": truth.label}, indent=2))
    return case_id
