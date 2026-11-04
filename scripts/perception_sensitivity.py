"""Run the perception-error propagation study and write perception_sensitivity.json.

Zero API cost: every perturbation rebuilds evidence from committed logs. See
docs/benchmarks/perception-sensitivity-preregistration.md for the design, fixed before any result was computed.

Usage: python scripts/perception_sensitivity.py
"""

import json
import statistics
import tempfile
from pathlib import Path

from telltale.config import CASES, DATA, ROOT
from telltale.pipeline.analyze import build_case_store
from telltale.pipeline.perception_sensitivity import (
    StudyCase,
    flip_margins,
    label_at,
    missed_onset_label,
    skewed,
    stability,
)

SHIFTS = (-2.0, -1.0, -0.5, -0.25, 0.25, 0.5, 1.0, 2.0)
ADAS_SKEWS = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
CAN_SKEWS = (-5.0, -1.0, 1.0, 5.0)
TAIL_ONSET_S = 2.0


def load_cases() -> list[StudyCase]:
    """Every case with ground truth. The study's scoring is the only reader of the expected labels."""
    cases = []
    for cases_dir, truth_dir in (
        (CASES, DATA / "ground_truth"),
        (DATA / "agent_bench/cases", DATA / "agent_bench/ground_truth"),
    ):
        for case_dir in sorted(p for p in cases_dir.iterdir() if (p / "case.json").exists()):
            truth_file = truth_dir / f"{case_dir.name}.json"
            if not truth_file.exists():
                continue
            truth = json.loads(truth_file.read_text())
            built = build_case_store(case_dir)
            cases.append(
                StudyCase(case_dir.name, case_dir, built.video, built.profile, truth["story"], truth["expected_label"])
            )
    return cases


def measured_errors() -> tuple[list[float], list[float]]:
    """Signed onset errors from the n=400 benchmark (scoring A), all and without the start-of-clip tail."""
    rows = [
        r
        for r in json.loads((ROOT / "video_bench.json").read_text())["rows"]
        if r.get("onset_t") is not None and r.get("alert_t") is not None
    ]
    errors = [r["onset_t"] - r["alert_t"] for r in rows]
    trimmed = [r["onset_t"] - r["alert_t"] for r in rows if r["onset_t"] >= TAIL_ONSET_S]
    return errors, trimmed


def main() -> None:
    cases = load_cases()
    errors, trimmed = measured_errors()
    per_case = []
    with tempfile.TemporaryDirectory() as work:
        for case in cases:
            base = label_at(case, 0.0)
            per_case.append(
                {
                    "case_id": case.case_id,
                    "story": case.story,
                    "expected": case.expected,
                    "base": base,
                    "base_correct": base == case.expected,
                    "onset_t": case.video.hazard_onset_t,
                    "impact_t": case.video.impact_t,
                    "shifts": {f"{d:+}": label_at(case, d) for d in SHIFTS},
                    "flip_margins": flip_margins(case),
                    "missed_onset_what_if": missed_onset_label(case),
                    "adas_skew": {f"{s:+}": skewed(case, Path(work), adas_s=s) for s in ADAS_SKEWS},
                    "can_skew": {f"{s:+}": skewed(case, Path(work), can_s=s) for s in CAN_SKEWS},
                }
            )
            print(f"{case.case_id}: {base} margins={per_case[-1]['flip_margins']}")
    stories = sorted({c.story for c in cases})
    result = {
        "n_cases": len(cases),
        "measured_errors": {"all": len(errors), "without_tail": len(trimmed), "median_all": statistics.median(errors)},
        "stability_all_errors": stability(cases, errors),
        "stability_without_tail": stability(cases, trimmed),
        "stability_by_story": {
            s: {
                "all": stability([c for c in cases if c.story == s], errors),
                "without_tail": stability([c for c in cases if c.story == s], trimmed),
            }
            for s in stories
        },
        "cases": per_case,
    }
    (ROOT / "perception_sensitivity.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=2))


if __name__ == "__main__":
    main()
