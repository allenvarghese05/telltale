from pathlib import Path

import pytest

import telltale.pipeline.recheck as rc
from telltale.core.schema import CheckResult, Claim
from telltale.pipeline.robust_bench import PlanItem


def test_robustness_run_paths_map_back_to_their_plan_items():
    root = Path("/c/agent_robust")
    assert rc.plan_item_for(root / "missing_evidence" / "pressure_lost" / "cand36-car-s5012.json", root) == PlanItem(
        "missing_evidence", "pressure_lost", "cand36-car-s5012", "missing_evidence/pressure_lost/cand36-car-s5012"
    )
    assert rc.plan_item_for(root / "lying_witness" / "cand36-car-s5017.json", root) == PlanItem(
        "lying_witness", "", "cand36-car-s5017", "lying_witness/cand36-car-s5017"
    )
    assert rc.plan_item_for(root / "repeat" / "run2" / "cand37-car-s1313.json", root) == PlanItem(
        "repeat", "run2", "cand37-car-s1313", "repeat/run2/cand37-car-s1313"
    )


def _row(text, status, reasons=()):
    return {
        "claim": {"text": text, "type": "timing", "evidence": ["X:a"], "assertion": None},
        "status": status,
        "reasons": list(reasons),
    }


def test_compare_lists_claims_whose_status_changed():
    after = [_row("a", "VERIFIED"), _row("b", "BLOCKED", ["interval meaning: ..."]), _row("c", "BLOCKED", ["n"])]
    before = {"a": "VERIFIED", "b": "VERIFIED", "c": "BLOCKED"}

    def check_before(claim: Claim, _store) -> CheckResult:
        return CheckResult(claim, before[claim.text], [])

    changed = rc.compare_claims(after, None, check_before)
    assert changed == [{"text": "b", "before": "VERIFIED", "after": "BLOCKED", "reason": "interval meaning: ..."}]


def test_summary_counts_before_and_after_and_verdict_changes():
    runs = [
        {
            "benchmark": "hard",
            "before": {"VERIFIED": 3, "UNCORROBORATED": 0, "BLOCKED": 0},
            "after": {"VERIFIED": 2, "UNCORROBORATED": 0, "BLOCKED": 1},
            "changed": [{"text": "b"}],
            "verdict_before": "VERIFIED",
            "verdict_after": "VERIFIED",
        },
        {
            "benchmark": "hard",
            "before": {"VERIFIED": 1, "UNCORROBORATED": 0, "BLOCKED": 0},
            "after": {"VERIFIED": 1, "UNCORROBORATED": 0, "BLOCKED": 0},
            "changed": [],
            "verdict_before": "REJECTED",
            "verdict_after": "REJECTED",
        },
    ]
    s = rc.summarize(runs)
    assert s["hard"] == {
        "runs": 2,
        "claims": 4,
        "before": {"VERIFIED": 4, "UNCORROBORATED": 0, "BLOCKED": 0},
        "after": {"VERIFIED": 3, "UNCORROBORATED": 0, "BLOCKED": 1},
        "runs_with_a_changed_claim": 1,
        "verdict_status_changes": 0,
    }


def test_summary_rejects_inconsistent_totals():
    bad = [
        {
            "benchmark": "x",
            "before": {"VERIFIED": 1, "UNCORROBORATED": 0, "BLOCKED": 0},
            "after": {"VERIFIED": 2, "UNCORROBORATED": 0, "BLOCKED": 0},
            "changed": [],
            "verdict_before": "VERIFIED",
            "verdict_after": "VERIFIED",
        }
    ]
    with pytest.raises(ValueError, match="claim totals differ"):
        rc.summarize(bad)
