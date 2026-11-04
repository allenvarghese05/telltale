"""Investigate and verify one case end to end, and write the replay bundle the static site renders.

Order of work: build the evidence store from the footage and the vehicle's logs, let the Muse Wonder agent
investigate it (or replay a cached run), then let the deterministic checker verify every claim and the verdict.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2

from telltale.config import AGENT_MODEL, CACHE, CASES, CLIPS, client
from telltale.core.manifest import get_clip
from telltale.core.schema import Claim, Fact, VideoFacts
from telltale.evidence.build import build_store
from telltale.evidence.store import EvidenceStore
from telltale.physics.counterfactual import counterfactual
from telltale.physics.profiles import PROFILES, VehicleProfile
from telltale.verify.checker import check_all, check_verdict
from telltale.video.facts import compute_video_facts
from telltale.video.scene import SceneSummary, scene_facts, summarize_scene
from telltale.video.witness import witness_facts

EVENT_LABELS = [
    ("VID:hazard_onset_t", "Becomes a hazard"),
    ("AV:first_seen_t", "Driver-assist detects it"),
    ("AV:brake_request_t", "Driver-assist commands braking"),
    ("AV:handoff_t", "Control handed to driver"),
    ("CAN:brake_request_t", "Brake request on CAN"),
    ("CAN:pressure_reached_t", "Brakes engage (60%)"),
    ("VID:impact_t", "Impact"),
]
THUMB_SIZE = (240, 135)


@dataclass(frozen=True)
class CaseEvidence:
    """Everything known about one case before the agent runs."""

    clip: dict
    profile: VehicleProfile
    tracks: dict
    video: VideoFacts
    store: EvidenceStore
    scene: SceneSummary
    red_team: str | None


def build_case_store(case_dir: Path) -> CaseEvidence:
    """Footage facts, witness, curated scene facts and the vehicle's logs, hashed into one evidence store."""
    case = json.loads((case_dir / "case.json").read_text())
    clip = get_clip(case["clip_id"])
    profile = PROFILES[case["profile"]]
    tracks = json.loads((CACHE / "sam" / f"{clip['clip_id']}.json").read_text())
    video = compute_video_facts(tracks, clip)
    witness_path = CACHE / "witness" / f"{clip['clip_id']}.json"
    witness = json.loads(witness_path.read_text()) if witness_path.exists() else None
    scene = summarize_scene(tracks, clip, witness["answers"] if witness else None)
    extra = scene_facts(scene) + (witness_facts(witness["answers"], witness["model"]) if witness else [])
    store = build_store(case_dir, video, profile, extra)
    return CaseEvidence(clip, profile, tracks, video, store, scene, case.get("red_team"))


def counterfactual_fn(store: EvidenceStore, profile: VehicleProfile) -> Callable[[float, float, float], dict]:
    """The agent's `run_counterfactual` tool: replay this case's physics with different timings."""
    v0 = float(store.get("CAN:speed_at_onset_mps").value)
    v_other = v0 - float(store.get("AV:rel_speed_mps").value)
    d0 = float(store.get("PHYS:gap_at_onset_m").value)
    t_end = float(store.get("VID:impact_t").value) - float(store.get("VID:hazard_onset_t").value) + 2.0

    def run(perception_s: float, command_s: float, tau_s: float) -> dict:
        r = counterfactual(
            v0, v_other, d0, profile, perception_s=perception_s, command_s=command_s, tau=tau_s, t_end=t_end
        )
        return {"contact": r.contact, "impact_speed_mps": r.impact_rel_speed, "min_gap_m": r.min_gap}

    return run


def agent_run(
    case_id: str,
    clip_id: str,
    store: EvidenceStore,
    profile: VehicleProfile,
    live: bool,
    cache_dir: Path | None = None,
) -> dict:
    """The investigator's run for this case. Replays the cached run unless `live`; a live run is cached."""
    path = (cache_dir or CACHE / "agent") / f"{case_id}.json"
    if path.exists() and not live:
        return json.loads(path.read_text())
    from telltale.agent.investigator import investigate
    from telltale.video.witness import recheck

    def witness_recheck(question: str, t0: float, t1: float, slug: str) -> Fact:
        return recheck(clip_id, question, t0, t1, slug)

    run = investigate(
        store,
        client(),
        counterfactual_fn=counterfactual_fn(store, profile),
        recheck_fn=witness_recheck,
        model=AGENT_MODEL,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, indent=2))
    return run


def check_run(run: dict, store: EvidenceStore) -> tuple[EvidenceStore, list[dict], dict, dict]:
    """Verify every claim and the verdict of one agent run against the store plus the facts its tools made."""
    full = store.extended([Fact(**f) for f in run["agent_facts"]]) if run["agent_facts"] else store
    claims = [
        Claim(
            text=str(c.get("text", "")),
            type=c.get("type", "other"),
            evidence=list(c.get("evidence", [])),
            assertion=c.get("assertion"),
        )
        for c in run["claims"]
    ]
    result = check_all(claims, full)
    rows = [{"claim": asdict(r.claim), "status": r.status, "reasons": r.reasons} for r in result["results"]]
    return full, rows, result["counts"], check_verdict(run["verdict"], full)


def _attach_thumbnails(case_id: str, clip: dict, events: list[dict]) -> None:
    """One frame per timeline event, for the incident strip. Missing frames leave `thumb` as None."""
    capture = cv2.VideoCapture(str(CLIPS / clip["file"]))
    for event in events:
        name = event["key"].split(":")[1]
        out = CACHE / "thumbs" / case_id / f"{name}.jpg"
        event["thumb"] = None
        if not out.exists():
            capture.set(cv2.CAP_PROP_POS_MSEC, event["t"] * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out), cv2.resize(frame, THUMB_SIZE))
        event["thumb"] = f"thumbs/{case_id}/{name}.jpg"
    capture.release()


def analyze(case_id: str, live: bool = False) -> dict:
    """Investigate and verify one case, write `cache/bundles/<case_id>.json`, and return the bundle."""
    case = build_case_store(CASES / case_id)
    clip, video, store = case.clip, case.video, case.store
    # A red-team case replays its hand-altered run even when `live` is asked for: re-running the agent would
    # quietly replace the alteration with a natural run still filed under the red-team label.
    run = agent_run(case_id, clip["clip_id"], store, case.profile, live and case.red_team is None)
    full, claims, counts, verdict = check_run(run, store)
    facts = {f.id: f.value for f in full.facts()}
    events = [
        {"key": key, "t": facts[key], "label": label, "source": key.split(":")[0]}
        for key, label in EVENT_LABELS
        if key in facts
    ]
    _attach_thumbnails(case_id, clip, events)
    noncausal = facts.get("ATTR:noncausal_faults", "none")
    verdict["noncausal_faults"] = [] if noncausal == "none" else noncausal.split(",")
    verdict["excess_s"] = {
        key.removeprefix("ATTR:excess_").removesuffix("_s"): value
        for key, value in facts.items()
        if key.startswith("ATTR:excess_")
    }
    bundle = {
        "case_id": case_id,
        "red_team": case.red_team,
        "clip_id": clip["clip_id"],
        "profile": case.profile.name,
        "video_url": f"media/{clip['file']}",
        "fps": clip["fps"],
        "width": clip["width"],
        "height": clip["height"],
        "lane_polygon": clip["ego_lane_polygon"],
        "target_boxes": case.tracks["objects"][video.target_object_id],
        "events": events,
        "series": {name: full.series(name) for name in ("can.speed_mps", "can.brake_pressure_kpa")},
        "facts": [asdict(f) for f in full.facts()],
        "scene": asdict(case.scene),
        "verdict": verdict,
        "claims": claims,
        "counts": counts,
        "digest": full.digest,
        "stale_agent_run": run.get("digest") != full.digest,
        "agent": {"model": run["model"], "tool_calls": run["tool_calls"]},
        "counterfactual_inputs": {
            "v_ego0": facts["CAN:speed_at_onset_mps"],
            "v_other": facts["CAN:speed_at_onset_mps"] - facts["AV:rel_speed_mps"],
            "d0": facts["PHYS:gap_at_onset_m"],
            "t_end": round(video.impact_t - video.hazard_onset_t + 2.0, 3),
            "measured": {
                "perception_s": facts.get("PHYS:perception_latency_s"),
                "command_s": facts.get("PHYS:command_latency_s"),
                "tau_s": facts.get("PHYS:brake_tau_est_s"),
            },
        },
    }
    out = CACHE / "bundles" / f"{case_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle))
    return bundle


def analyze_all(live: bool = False) -> list[str]:
    """Analyze every case; returns one summary line per case (the CLI prints them)."""
    lines = []
    for case_dir in sorted(p for p in CASES.iterdir() if (p / "case.json").exists()):
        bundle = analyze(case_dir.name, live=live)
        verdict = bundle["verdict"]
        lines.append(f"{case_dir.name} {verdict['agent_label']} {verdict['status']} {bundle['counts']}")
    return lines
