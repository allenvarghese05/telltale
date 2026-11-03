"""Build the static replay site (Hugging Face Static Space and `telltale serve`) from cached bundles."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np

from telltale.config import CACHE, CLIPS, ROOT
from telltale.physics.counterfactual import counterfactual
from telltale.physics.profiles import PROFILES
from telltale.report.render import render_html

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
    }


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
        (out / "cases" / f"{case_id}.json").write_text(json.dumps(bundle))
        (out / "cf" / f"{case_id}.json").write_text(json.dumps(counterfactual_grid(bundle)))
        (out / "reports" / f"{case_id}.html").write_text(render_html(bundle))
        clip = Path(bundle["video_url"]).name
        if not (out / "media" / clip).exists():
            shutil.copy(clips_dir / clip, out / "media" / clip)
        if (thumbs_dir / case_id).is_dir():
            shutil.copytree(thumbs_dir / case_id, out / "thumbs" / case_id)
        index.append({"case_id": case_id, "clip_id": bundle["clip_id"], "profile": bundle["profile"]})
    (out / "cases.json").write_text(json.dumps(index))
    (out / "README.md").write_text(SPACE_README)
    return out
