"""How often does a perception error change the verdict?

Each perturbation builds a modified `VideoFacts`, or a copy of a case's logs with shifted clocks, and calls the
existing `build_store`. That re-runs alignment, the counterfactual and `attribute`, and the label read back is
`ATTR:label`. Nothing here re-implements physics. Ground truth is compared only in `stability`, the study's own
scoring; the checker and agent paths never see it.
"""

from __future__ import annotations

import collections
import dataclasses
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from telltale.core.schema import VideoFacts
from telltale.evidence.build import build_store
from telltale.logs.mcap_io import read_adas_mcap, write_adas_mcap
from telltale.physics.attribution import Measured, attribute
from telltale.physics.profiles import VehicleProfile

# Only the timestamp moves. Re-encoding frames would lose whether an identifier is 29-bit, which truck J1939 needs.
CANDUMP_TIME = re.compile(r"^\(([0-9.]+)\)", re.MULTILINE)


@dataclass(frozen=True)
class StudyCase:
    case_id: str
    case_dir: Path
    video: VideoFacts
    profile: VehicleProfile
    story: str
    expected: str


def label_at(case: StudyCase, delta: float, case_dir: Path | None = None) -> str | None:
    """The attribution with the hazard onset moved by `delta` seconds; None when that onset is impossible.

    A shifted onset at or before the first frame, or at or after impact, cannot have been observed. The unshifted
    onset is the measurement itself and is always used, even when SAM placed it on the first frame.
    """
    onset = case.video.hazard_onset_t + delta
    if onset >= case.video.impact_t or (delta != 0.0 and onset <= 0.0):
        return None
    video = dataclasses.replace(case.video, hazard_onset_t=onset)
    return str(build_store(case_dir or case.case_dir, video, case.profile).get("ATTR:label").value)


def flip_margins(case: StudyCase, step: float = 0.05, span: float = 3.0) -> dict[str, float | None]:
    """The smallest earlier and later onset shift that changes the label; None if none does while feasible."""
    base = label_at(case, 0.0)
    margins: dict[str, float | None] = {}
    for side, sign in (("early", -1), ("late", 1)):
        margins[side] = None
        for k in range(1, round(span / step) + 1):
            label = label_at(case, sign * k * step)
            if label is None:
                break
            if label != base:
                margins[side] = round(k * step, 4)
                break
    return margins


def missed_onset_label(case: StudyCase) -> str:
    """What-if: attribution with perception latency unknown and every other measured value unchanged.

    The pipeline itself never reaches this: when SAM misses the struck vehicle, `compute_video_facts` raises and no
    case is built. This asks what the verdict would rest on if the onset were simply absent.
    """
    store = build_store(case.case_dir, case.video, case.profile)

    def fact(fid: str):
        return store.get(fid).value if store.has(fid) else None

    measured = Measured(
        None,
        fact("PHYS:command_latency_s"),
        fact("PHYS:actuation_latency_s"),
        fact("PHYS:handoff_margin_s"),
        fact("PHYS:cf_nominal_contact"),
        bool(fact("DATA:brake_log_complete")),
    )
    return attribute(measured, case.profile).label


def skewed(case: StudyCase, workdir: Path, adas_s: float = 0.0, can_s: float = 0.0) -> dict:
    """Rebuild from a copy of the case whose ADAS or CAN timestamps are shifted, and report alignment and label."""
    base = build_store(case.case_dir, case.video, case.profile)
    copy = workdir / f"{case.case_id}-adas{adas_s:+.2f}-can{can_s:+.2f}"
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(case.case_dir, copy)
    if adas_s:
        messages = read_adas_mcap(copy / "adas.mcap")
        write_adas_mcap(
            copy / "adas.mcap",
            [(topic, round((t + adas_s) * 1e9), payload) for topic, items in messages.items() for t, payload in items],
        )
    if can_s:
        log = copy / "vehicle.can.log"
        log.write_text(CANDUMP_TIME.sub(lambda m: f"({float(m.group(1)) + can_s:.6f})", log.read_text()))
    store = build_store(copy, case.video, case.profile)
    expected_av = float(base.get("AV:clock_offset_s").value) - adas_s
    return {
        "label": str(store.get("ATTR:label").value),
        "av_offset_error_s": round(float(store.get("AV:clock_offset_s").value) - expected_av, 4),
    }


def stability(cases: list[StudyCase], errors: list[float]) -> dict:
    """Apply every error to every case: how often the verdict survives, and how often it stays correct."""
    feasible = stable = correct = infeasible = 0
    flips: collections.Counter[str] = collections.Counter()
    for case in cases:
        base = label_at(case, 0.0)
        for error in errors:
            label = label_at(case, error)
            if label is None:
                infeasible += 1
                continue
            feasible += 1
            stable += label == base
            correct += label == case.expected
            if label != base:
                flips[f"{base}->{label}"] += 1
    return {
        "cases": len(cases),
        "draws": len(cases) * len(errors),
        "feasible": feasible,
        "stable": stable,
        "correct": correct,
        "infeasible": infeasible,
        "flips": dict(flips),
    }
