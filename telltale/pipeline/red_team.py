"""A red-team demo case: a real agent run with one claim and the verdict altered by hand.

Every natural demo case passes the checker, so a viewer never sees it refuse anything. This builds one case,
labelled as altered everywhere it appears, from a copy of a real cached run: one claim's figure is changed in
both its text and its assertion, and the verdict is replaced. The deterministic checker then runs on it exactly
as on any other case. Nothing here touches the checker, and the real run is never edited in place.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

from telltale.config import CACHE, CASES
from telltale.core.schema import LABELS
from telltale.web.export import SAFE_ID

RED_TEAM_NOTE = (
    "Red-team: one claim and the investigator's verdict were altered by hand to show the checker at work. "
    "This is not a natural agent output."
)
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def alter_run(run: dict, claim_index: int, value: float, verdict: str, rewrite: dict[str, str] | None = None) -> dict:
    """A copy of `run` with one claim's figure replaced in its text and assertion, and a new verdict.

    `rewrite` swaps phrases in that claim's text, so an altered figure reads coherently: a latency moved under
    its threshold should say "below", as a motivated investigator would write it.
    """
    if verdict not in LABELS:
        raise ValueError(f"{verdict!r} is not a verdict label; expected one of {LABELS}")
    altered = copy.deepcopy(run)
    claim = altered["claims"][claim_index]
    assertion = claim.get("assertion") or {}
    original = assertion.get("equals")
    if isinstance(original, bool) or not isinstance(original, (int, float)):
        raise ValueError(f"claim {claim_index} has no numeric assertion to alter")
    quoted = next((t for t in NUMBER.findall(claim["text"]) if float(t) == original), None)
    if quoted is None:
        raise ValueError(f"claim {claim_index} text does not quote its figure {original}: {claim['text']!r}")
    whole_number = re.compile(rf"(?<![\d.]){re.escape(quoted)}(?![\d.])")
    claim["text"] = whole_number.sub(f"{value:g}", claim["text"], count=1)
    for old, new in (rewrite or {}).items():
        if old not in claim["text"]:
            raise ValueError(f"claim {claim_index} text does not contain {old!r}: {claim['text']!r}")
        claim["text"] = claim["text"].replace(old, new)
    assertion["equals"] = value
    altered["verdict"] = verdict
    altered["red_team"] = {
        "claim_index": claim_index,
        "original_value": original,
        "altered_value": value,
        "original_verdict": run["verdict"],
        "altered_verdict": verdict,
        "rewrite": dict(rewrite or {}),
    }
    return altered


def make_red_team_case(
    source_case_id: str,
    red_team_id: str,
    claim_index: int,
    value: float,
    verdict: str,
    rewrite: dict[str, str] | None = None,
    cases_dir: Path = CASES,
    agent_dir: Path = CACHE / "agent",
) -> str:
    """Copy a real case and its cached run under a new id, mark the case as red-team, and alter the run."""
    if not SAFE_ID.match(red_team_id):
        raise ValueError(f"unsafe case id {red_team_id!r}")
    target = cases_dir / red_team_id
    if target.exists():
        existing = json.loads((target / "case.json").read_text())
        if "red_team" not in existing:
            raise FileExistsError(f"{target} exists and is not a red-team case; refusing to overwrite it")
        shutil.rmtree(target)
    shutil.copytree(cases_dir / source_case_id, target)
    case = json.loads((target / "case.json").read_text())
    (target / "case.json").write_text(json.dumps({**case, "case_id": red_team_id, "red_team": RED_TEAM_NOTE}))
    run = json.loads((agent_dir / f"{source_case_id}.json").read_text())
    altered = alter_run(run, claim_index, value, verdict, rewrite)
    (agent_dir / f"{red_team_id}.json").write_text(json.dumps(altered, indent=2))
    return red_team_id
