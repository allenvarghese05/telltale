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
from telltale.core.manifest import load_manifest
from telltale.logs.generate import HARD_STORIES, GenerationError, generate_case
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
BENCH_PROFILES = ("car", "truck")
TURN_LIMIT_MESSAGE = "turn limit"


def clip_ids() -> list[str]:
    return list(load_manifest()["clips"])


def hard_plan(clips, seed: int = PLAN_SEED) -> list[tuple[str, str, str, int]]:
    """Every (clip, profile, story) in one fixed shuffled order, each with its own case seed."""
    combos = [(c, p, s) for c in clips for p in BENCH_PROFILES for s in HARD_STORIES]
    random.Random(seed).shuffle(combos)
    return [(c, p, s, HARD_SEED_BASE + i) for i, (c, p, s) in enumerate(combos)]


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
    }


def _load(path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _investigate(case_id: str, clip_id: str, case) -> dict | None:
    """The agent's run, or None when it never submitted. A run that never submitted is remembered, not retried."""
    marker = HARD_CACHE / f"{case_id}.no_verdict.json"
    if marker.exists():
        return None
    try:
        return agent_run(case_id, clip_id, case.store, case.profile, live=False, cache_dir=HARD_CACHE)
    except RuntimeError as exc:
        if TURN_LIMIT_MESSAGE not in str(exc):
            raise
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"case": case_id, "error": str(exc)}))
        return None


def run_hard_bench(n: int = 30) -> dict:
    """Score the first `n` usable cases of the fixed plan. Agent runs are cached, so re-running resumes."""
    skipped_path = BENCH_DIR / "hard_skipped.json"
    skipped = _load(skipped_path)
    rows = []
    for clip_id, profile, story, case_seed in hard_plan(clip_ids()):
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
        run = _investigate(case_id, clip_id, case)
        if run is None:
            row |= {"agent": None, "independent": measured, "status": "NO_VERDICT", "blocked": []}
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
            }
        rows.append(row)
        log.info("%s %s agent=%s %s %s", case_id, story, row["agent"], row["status"], row["counts"])
    result = {"summary": summarize_hard(rows), "rows": rows, "skipped": [f"{k}: {v}" for k, v in skipped.items()]}
    RESULTS.write_text(json.dumps(result, indent=2))
    return result
