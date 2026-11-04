"""Build the static replay site (Hugging Face Static Space and `telltale serve`) from cached bundles."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from html import escape
from pathlib import Path

import numpy as np

from telltale.config import CACHE, CLIPS, ROOT
from telltale.physics.counterfactual import counterfactual
from telltale.physics.profiles import PROFILES
from telltale.report.render import render_html
from telltale.web.narrative import Section, incident_report

STATIC = Path(__file__).parent / "static"
SITE = ROOT / "site"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
PERCEPTION_GRID = np.round(np.arange(0.0, 2.5001, 0.05), 2)
TAU_GRID = np.round(np.arange(0.05, 2.0001, 0.05), 2)
SPACE_README = """---
title: Telltale
emoji: 🚦
colorFrom: gray
colorTo: red
sdk: static
pinned: false
---

Replay demo of Telltale: Meta AI investigates vehicle crashes; a deterministic checker makes it auditable.
Source: https://github.com/allenvarghese05/telltale
"""


def _kmh(mps: float) -> float:
    return round(float(mps) * 3.6, 1)


def exact_outcomes(facts: dict) -> dict:
    """The checker's own impact speeds (km/h, 0.0 = avoided), so the page's sentence matches the incident report.

    The grid below is sampled, so its nearest cell can differ slightly from the exact replay at the measured timings.
    """
    measured = facts.get("PHYS:actual_impact_speed_mps")
    contact = facts.get("PHYS:cf_nominal_contact")
    nominal = None
    if contact is False:
        nominal = 0.0
    elif contact is True and "PHYS:cf_nominal_impact_speed_mps" in facts:
        nominal = _kmh(facts["PHYS:cf_nominal_impact_speed_mps"])
    return {"measured": None if measured is None else _kmh(measured), "nominal": nominal}


def counterfactual_grid(bundle: dict) -> dict:
    """Impact speed (km/h, 0.0 = avoided) for every detection delay x brake time constant."""
    inputs = bundle["counterfactual_inputs"]
    profile = PROFILES[bundle["profile"]]
    command = inputs["measured"].get("command_s") or profile.nominal["command_s"]
    impact = []
    for perception in PERCEPTION_GRID:
        row = []
        for tau in TAU_GRID:
            result = counterfactual(
                inputs["v_ego0"],
                inputs["v_other"],
                inputs["d0"],
                profile,
                perception_s=float(perception),
                command_s=command,
                tau=float(tau),
                t_end=inputs["t_end"],
            )
            row.append(round(result.impact_rel_speed * 3.6, 1) if result.contact else 0.0)
        impact.append(row)
    return {
        "perception_s": PERCEPTION_GRID.tolist(),
        "tau_s": TAU_GRID.tolist(),
        "impact_kmh": impact,
        "measured": inputs["measured"],
        "nominal": {"perception_s": profile.nominal["perception_s"], "tau_s": profile.tau_nominal},
        "outcome_kmh": exact_outcomes({f["id"]: f["value"] for f in bundle.get("facts", [])}),
    }


REPORT_EVIDENCE_HEADING = "<h2>Evidence</h2>"


def report_with_narrative(bundle: dict, sections: list[Section]) -> str:
    """The printable report, with the plain-English account placed just before its raw evidence table."""
    html = render_html(bundle)
    if REPORT_EVIDENCE_HEADING not in html:
        raise ValueError(f"printable report has no {REPORT_EVIDENCE_HEADING} heading to place the narrative before")
    body = "".join(
        f"<h3>{escape(s.title)}</h3><p>{' '.join(escape(line.text) for line in s.sentences)}</p>" for s in sections
    )
    return html.replace(REPORT_EVIDENCE_HEADING, f"<h2>Incident report</h2>{body}{REPORT_EVIDENCE_HEADING}", 1)


def export_site(
    bundles_dir: Path = CACHE / "bundles",
    out: Path = SITE,
    clips_dir: Path = CLIPS,
    thumbs_dir: Path = CACHE / "thumbs",
) -> Path:
    """Copy the page, then write one bundle, avoidance map, report, clip and thumbnail set per case."""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out)
    for sub in ("cases", "cf", "reports", "media", "thumbs"):
        (out / sub).mkdir()
    index = []
    for path in sorted(bundles_dir.glob("*.json")):
        bundle = json.loads(path.read_text())
        case_id = bundle["case_id"]
        if not SAFE_ID.match(case_id):
            raise ValueError(f"unsafe case id {case_id!r} in {path.name}")
        sections = incident_report(bundle)
        case = {**bundle, "narrative": [asdict(s) for s in sections]}
        (out / "cases" / f"{case_id}.json").write_text(json.dumps(case))
        (out / "cf" / f"{case_id}.json").write_text(json.dumps(counterfactual_grid(bundle)))
        (out / "reports" / f"{case_id}.html").write_text(report_with_narrative(bundle, sections))
        clip = Path(bundle["video_url"]).name
        if not (out / "media" / clip).exists():
            shutil.copy(clips_dir / clip, out / "media" / clip)
        if (thumbs_dir / case_id).is_dir():
            shutil.copytree(thumbs_dir / case_id, out / "thumbs" / case_id)
        index.append({"case_id": case_id, "clip_id": bundle["clip_id"], "profile": bundle["profile"]})
    (out / "cases.json").write_text(json.dumps(index))
    (out / "README.md").write_text(SPACE_README)
    return out
