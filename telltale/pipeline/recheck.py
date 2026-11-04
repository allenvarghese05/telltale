"""Re-check every committed agent run under the current checker, offline, against an earlier checker.

No model is called: each run is replayed from its cache against the same evidence store it was checked on (for
the robustness runs, the same tampered store, rebuilt by the benchmark's own code). The result lists every claim
whose status changed and confirms whether any verdict outcome changed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from telltale.config import CACHE, CASES, DATA
from telltale.core.schema import CheckResult, Claim
from telltale.evidence.store import EvidenceStore
from telltale.pipeline.analyze import build_case_store, check_run
from telltale.pipeline.robust_bench import PlanItem, natural_pool, tampered_store

STATUSES = ("VERIFIED", "UNCORROBORATED", "BLOCKED")
BENCH_CASES = DATA / "agent_bench" / "cases"


def plan_item_for(path: Path, root: Path) -> PlanItem:
    """The robustness plan item a cached run file belongs to, from its place under the cache directory."""
    parts = path.relative_to(root).with_suffix("").parts
    condition, case = parts[0], parts[-1]
    variant = parts[1] if len(parts) == 3 else ""
    return PlanItem(condition, variant, case, "/".join(parts))


def committed_runs() -> list[tuple[str, str, Path, Path, PlanItem | None]]:
    """(benchmark, run key, run file, case directory, robustness plan item or None) for every committed run."""
    out = []
    for benchmark, cache_dir, case_root in (
        ("demo", CACHE / "agent", CASES),
        ("agent_bench", CACHE / "agent_bench", BENCH_CASES),
        ("hard", CACHE / "agent_hard", BENCH_CASES),
        ("confusable", CACHE / "agent_confusable", BENCH_CASES),
    ):
        for path in sorted(cache_dir.glob("*.json")):
            if not path.name.endswith(".no_verdict.json"):
                out.append((benchmark, path.stem, path, case_root / path.stem, None))
    _, dirs = natural_pool()
    root = CACHE / "agent_robust"
    for path in sorted(root.rglob("*.json")):
        item = plan_item_for(path, root)
        out.append(("robustness", item.cache_key, path, dirs[item.case], item))
    return out


def compare_claims(
    rows_after: list[dict], store: EvidenceStore | None, check_before: Callable[[Claim, EvidenceStore], CheckResult]
) -> list[dict]:
    """Claims whose status differs between the earlier checker and the current one."""
    changed = []
    for row in rows_after:
        before = check_before(Claim(**row["claim"]), store)
        if before.status != row["status"]:
            changed.append(
                {
                    "text": row["claim"]["text"],
                    "before": before.status,
                    "after": row["status"],
                    "reason": (row["reasons"] or [""])[0],
                }
            )
    return changed


def recheck_run(run: dict, store: EvidenceStore, check_before: Callable, verdict_before: Callable) -> dict:
    """One run under both checkers: claim counts before and after, changed claims, and both verdict outcomes."""
    full, rows, counts, verdict = check_run(run, store)
    changed = compare_claims(rows, full, check_before)
    before = dict(counts)
    for c in changed:
        before[c["after"]] -= 1
        before[c["before"]] += 1
    return {
        "before": before,
        "after": counts,
        "changed": changed,
        "verdict_before": verdict_before(run["verdict"], full)["status"],
        "verdict_after": verdict["status"],
    }


def summarize(runs: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in runs:
        if sum(r["before"].values()) != sum(r["after"].values()):
            raise ValueError("claim totals differ between checkers")
        s = out.setdefault(
            r["benchmark"],
            {
                "runs": 0,
                "claims": 0,
                "before": dict.fromkeys(STATUSES, 0),
                "after": dict.fromkeys(STATUSES, 0),
                "runs_with_a_changed_claim": 0,
                "verdict_status_changes": 0,
            },
        )
        s["runs"] += 1
        s["claims"] += sum(r["after"].values())
        for k in STATUSES:
            s["before"][k] += r["before"][k]
            s["after"][k] += r["after"][k]
        s["runs_with_a_changed_claim"] += bool(r["changed"])
        s["verdict_status_changes"] += r["verdict_before"] != r["verdict_after"]
    return out


def recheck_all(check_before: Callable, verdict_before: Callable) -> dict:
    """Every committed run, re-checked. `check_before` and `verdict_before` come from the earlier checker."""

    runs = []
    for benchmark, key, path, case_dir, item in committed_runs():
        case = build_case_store(case_dir)
        store = case.store if item is None else tampered_store(item, case.store, case.profile)[0]
        result = recheck_run(json.loads(path.read_text()), store, check_before, verdict_before)
        runs.append({"benchmark": benchmark, "run": key, **result})
    return {
        "summary": summarize(runs),
        "changed_claims": [{"benchmark": r["benchmark"], "run": r["run"], **c} for r in runs for c in r["changed"]],
        "runs": runs,
    }
