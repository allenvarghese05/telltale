"""Build the static replay site (Hugging Face Static Space and `telltale serve`) from cached bundles."""

from __future__ import annotations

import hashlib
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
from telltale.pipeline.investigate_clip import SHOWCASE_BUNDLES
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


VIDEO_KEYS = ("clip_id", "video_url", "fps", "width", "height", "lane_polygon", "tracks", "report")
GEOMETRIES = ("forward", "cross-path")


def _copy_clip(video_url: str, out: Path, clips_dir: Path) -> None:
    clip = Path(video_url).name
    if not (out / "media" / clip).exists():
        shutil.copy(clips_dir / clip, out / "media" / clip)


def video_case(bundle: dict) -> dict:
    """A video-only case for the site, by allowlist, so a verdict or claim can never reach that page.

    `geometry` is optional and annotated by a person: "cross-path" marks a crash the 1-D physics cannot attribute.
    """
    if not SAFE_ID.match(str(bundle.get("clip_id", ""))):
        raise ValueError(f"unsafe clip id {bundle.get('clip_id')!r} in a video-only bundle")
    case = {key: bundle[key] for key in VIDEO_KEYS}
    if "geometry" in bundle:
        if bundle["geometry"] not in GEOMETRIES:
            raise ValueError(f"unknown crash geometry {bundle['geometry']!r} for {case['clip_id']}")
        case["geometry"] = bundle["geometry"]
    return case


def publish_video_case(bundle: dict, out: Path, clips_dir: Path = CLIPS) -> None:
    """Add or replace one video-only case in an already-built site, without rebuilding the rest."""
    case = video_case(bundle)
    (out / "video").mkdir(exist_ok=True)
    (out / "video" / f"{case['clip_id']}.json").write_text(json.dumps(case))
    _copy_clip(case["video_url"], out, clips_dir)
    index_path = out / "videos.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else []
    if not any(entry["clip_id"] == case["clip_id"] for entry in index):
        index.append({"clip_id": case["clip_id"]})
    index_path.write_text(json.dumps(sorted(index, key=lambda entry: entry["clip_id"])))


TRACK_STEP = 2  # every second frame: smooth enough to draw at 30 fps, half the size


def clip_tracks(sam: dict) -> dict:
    """Every SAM-tracked vehicle for one clip, compact for the page: [frame, left, top, right, bottom] in pixels."""
    return {
        "fps": sam["fps"],
        "width": sam["width"],
        "height": sam["height"],
        "objects": {
            oid: [[d["frame"], *(round(v) for v in d["box"])] for d in dets if d["frame"] % TRACK_STEP == 0]
            or [[d["frame"], *(round(v) for v in d["box"])] for d in dets[:1]]
            for oid, dets in sam["objects"].items()
        },
    }


PAGES = ("index.html", "clips.html")
ASSETS = ("app.js", "clips.js", "site.js", "style.css")


def stamp_build(out: Path) -> str:
    """Version every page's assets and data by the site's content, so a new deploy is never served stale.

    The id is a hash of every data and asset file in the built site, so it changes exactly when they do.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.suffix in {".json", ".js", ".css"}):
        digest.update(path.relative_to(out).as_posix().encode())
        digest.update(path.read_bytes())
    build = digest.hexdigest()[:10]
    for page in PAGES:
        html = (out / page).read_text()
        for asset in ASSETS:
            html = html.replace(f'"{asset}"', f'"{asset}?v={build}"')
        html = html.replace("<head>", f'<head>\n  <meta name="build" content="{build}">', 1)
        (out / page).write_text(html)
    return build


def export_site(
    bundles_dir: Path = CACHE / "bundles",
    out: Path = SITE,
    clips_dir: Path = CLIPS,
    thumbs_dir: Path = CACHE / "thumbs",
    video_bundles_dir: Path = SHOWCASE_BUNDLES,
    uploads_dir: Path | None = None,
    sam_dir: Path = CACHE / "sam",
) -> Path:
    """Copy the pages, write every investigated case and every video-only case, plus their clips."""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out)
    for sub in ("cases", "cf", "reports", "media", "thumbs", "tracks"):
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
        _copy_clip(bundle["video_url"], out, clips_dir)
        if (thumbs_dir / case_id).is_dir():
            shutil.copytree(thumbs_dir / case_id, out / "thumbs" / case_id)
        index.append({"case_id": case_id, "clip_id": bundle["clip_id"], "profile": bundle["profile"]})
    (out / "cases.json").write_text(json.dumps(index))
    for clip_id in sorted({entry["clip_id"] for entry in index}):
        if not SAFE_ID.match(clip_id):
            raise ValueError(f"unsafe clip id {clip_id!r}")
        if (sam_dir / f"{clip_id}.json").exists():
            sam = json.loads((sam_dir / f"{clip_id}.json").read_text())
            (out / "tracks" / f"{clip_id}.json").write_text(json.dumps(clip_tracks(sam)))
    (out / "videos.json").write_text("[]")
    for path in sorted(video_bundles_dir.glob("*.json")):
        publish_video_case(json.loads(path.read_text()), out, clips_dir)
    # A person's own uploads are local only: included when asked for, never in the hosted export.
    if uploads_dir is not None:
        for path in sorted((uploads_dir / "video_bundles").glob("*.json")):
            publish_video_case(json.loads(path.read_text()), out, uploads_dir / "clips")
    (out / "README.md").write_text(SPACE_README)
    stamp_build(out)
    return out
