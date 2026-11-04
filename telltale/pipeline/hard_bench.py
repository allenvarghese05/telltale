"""Hard-case agent benchmark: does the checker catch real agent mistakes when the call is genuinely close?

Cases come from the hard generator stories (two faults decided by under 0.1 s, a fault just over its limit next to
a near miss, an unavoidable crash with a fault that did not matter), on car and truck, with larger clock skews.
The expected label is the deterministic attribution of the drawn truth, and a draw is used only when the evidence
pipeline, reading the logs blind, reaches the same label. Ground truth is read here, by scoring code only.
Criteria are fixed in `docs/benchmarks/hard-cases-preregistration.md`.
"""

from __future__ import annotations

import json
import logging
import random
import shutil

from telltale.config import CACHE, DATA, ROOT
from telltale.logs.generate import CONFUSABLE_STORIES, HARD_STORIES, GenerationError, generate_case
from telltale.physics.profiles import PROFILES
from telltale.pipeline.agent_bench import summarize
from telltale.pipeline.analyze import agent_run, build_case_store, check_run
from telltale.pipeline.demo import clip_timing

log = logging.getLogger(__name__)
BENCH_DIR = DATA / "agent_bench"
HARD_CACHE = CACHE / "agent_hard"
RESULTS = ROOT / "agent_bench_hard.json"
HARD_SEED_BASE = 7000
PLAN_SEED = 11
CONFUSABLE_CACHE = CACHE / "agent_confusable"
CONFUSABLE_RESULTS = ROOT / "agent_bench_confusable.json"
CONFUSABLE_SEED_BASE = 8000
CONFUSABLE_PLAN_SEED = 13
INTERVAL_MEANING = "interval meaning"
BENCH_CLIPS = ("cand36", "cand37", "cand38", "cand63")  # the demo clips the committed hard cases used
BENCH_PROFILES = ("car", "truck")
TURN_LIMIT_MESSAGE = "turn limit"


def clip_ids() -> list[str]:
    """The clips these benches draw on, pinned: the manifest has grown, and the plan must not move with it."""
    return list(BENCH_CLIPS)


def hard_plan(
    clips, seed: int = PLAN_SEED, stories: tuple[str, ...] = HARD_STORIES, seed_base: int = HARD_SEED_BASE
) -> list[tuple[str, str, str, int]]:
    """Every (clip, profile, story) in one fixed shuffled order, each with its own case seed."""
    combos = [(c, p, s) for c in clips for p in BENCH_PROFILES for s in stories]
    random.Random(seed).shuffle(combos)
    return [(c, p, s, seed_base + i) for i, (c, p, s) in enumerate(combos)]


def _breakdown(rows: list[dict], key: str) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        bucket = out.setdefault(r[key], {"n": 0, "agent_correct": 0})
        bucket["n"] += 1
        bucket["agent_correct"] += r["agent"] == r["expected"]
    return dict(sorted(out.items()))


def summarize_hard(rows: list[dict]) -> dict:
    return {
        **summarize(rows),
        "no_verdict": sum(r["status"] == "NO_VERDICT" for r in rows),
        "by_profile": _breakdown(rows, "profile"),
        "by_family": _breakdown(rows, "family"),
        "claims_blocked_interval_meaning": sum(
            any(r.startswith(INTERVAL_MEANING) for r in b["reasons"]) for row in rows for b in row.get("blocked", [])
        ),
    }


def _load(path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _investigate(case_id: str, clip_id: str, case, cache_dir) -> dict | None:
    """The agent's run, or None when it never submitted. A run that never submitted is remembered, not retried."""
    marker = cache_dir / f"{case_id}.no_verdict.json"
    if marker.exists():
        return None
    try:
        return agent_run(case_id, clip_id, case.store, case.profile, live=False, cache_dir=cache_dir)
    except RuntimeError as exc:
        if TURN_LIMIT_MESSAGE not in str(exc):
            raise
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"case": case_id, "error": str(exc)}))
        return None


def run_hard_bench(n: int = 30) -> dict:
    """Score the first `n` usable hard cases of the fixed plan. Agent runs are cached, so re-running resumes."""
    plan = hard_plan(clip_ids())
    return _run_plan(plan, n, BENCH_DIR / "hard_skipped.json", HARD_CACHE, RESULTS)


def run_confusable_bench(n: int = 20) -> dict:
    """The confusable-timeline cases, criteria in `docs/benchmarks/confusable-preregistration.md`."""
    plan = hard_plan(clip_ids(), CONFUSABLE_PLAN_SEED, CONFUSABLE_STORIES, CONFUSABLE_SEED_BASE)
    return _run_plan(plan, n, BENCH_DIR / "confusable_skipped.json", CONFUSABLE_CACHE, CONFUSABLE_RESULTS)


def _run_plan(plan, n: int, skipped_path, cache_dir, results) -> dict:
    """Generate, screen, investigate and score plan items in order until `n` cases are scored."""
    skipped = _load(skipped_path)
    rows = []
    for clip_id, profile, story, case_seed in plan:
        if len(rows) >= n:
            break
        case_id = f"{clip_id}-{profile}-s{case_seed:04d}"
        if case_id in skipped:
            continue
        case_dir, gt_path = BENCH_DIR / "cases" / case_id, BENCH_DIR / "ground_truth" / f"{case_id}.json"
        if not case_dir.exists():
            try:
                generate_case(
                    clip_timing(clip_id), PROFILES[profile], story, case_seed, BENCH_DIR / "cases", gt_path.parent
                )
            except GenerationError as exc:
                skipped[case_id] = f"{story}: {exc}"
                _save(skipped_path, skipped)
                continue
        case = build_case_store(case_dir)
        expected = json.loads(gt_path.read_text())["expected_label"]
        measured = case.store.get("ATTR:label").value
        if measured != expected:
            shutil.rmtree(case_dir)
            gt_path.unlink()
            skipped[case_id] = f"{story}: blind pipeline measured {measured}, drawn truth gives {expected}"
            _save(skipped_path, skipped)
            continue
        excess = {
            f.id.removeprefix("ATTR:excess_").removesuffix("_s"): f.value
            for f in case.store.facts()
            if f.id.startswith("ATTR:excess_")
        }
        row = {
            "case": case_id,
            "profile": profile,
            "story": story,
            "family": story.split("_")[0],
            "expected": expected,
            "excess": excess,
        }
        run = _investigate(case_id, clip_id, case, cache_dir)
        if run is None:
            row |= {"agent": None, "independent": measured, "status": "NO_VERDICT", "blocked": [], "claims": []}
            row["counts"] = {"VERIFIED": 0, "UNCORROBORATED": 0, "BLOCKED": 0}
        else:
            _, claims, counts, verdict = check_run(run, case.store)
            row |= {
                "agent": run["verdict"],
                "independent": verdict["independent_label"],
                "status": verdict["status"],
                "counts": counts,
                "blocked": [
                    {"text": c["claim"]["text"], "reasons": c["reasons"]} for c in claims if c["status"] == "BLOCKED"
                ],
                "claims": [
                    {"text": c["claim"]["text"], "evidence": c["claim"]["evidence"], "status": c["status"]}
                    for c in claims
                ],
            }
        rows.append(row)
        log.info("%s %s agent=%s %s %s", case_id, story, row["agent"], row["status"], row["counts"])
    result = {"summary": summarize_hard(rows), "rows": rows, "skipped": [f"{k}: {v}" for k, v in skipped.items()]}
    results.write_text(json.dumps(result, indent=2))
    return result
