"""The thesis benchmark: Muse Wonder's verdicts alone, versus the same verdicts after the deterministic checker.

Cases are generated blind on the demo clips; the injected story is the answer key. Ground truth is read here,
by scoring code only, never by the agent or the checker.
"""

from __future__ import annotations

import json
import logging
import random

from telltale.config import CACHE, DATA, ROOT
from telltale.core.manifest import load_manifest
from telltale.logs.generate import EXPECTED, STORIES, GenerationError, generate_case
from telltale.physics.profiles import CAR
from telltale.pipeline.analyze import agent_run, build_case_store, check_run
from telltale.pipeline.demo import clip_timing

log = logging.getLogger(__name__)
BENCH_DIR = DATA / "agent_bench"
SEED_BASE = 5000


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    wrong = [r for r in rows if r["agent"] != r["expected"]]
    return {
        "n": n,
        "agent_accuracy": round(sum(r["agent"] == r["expected"] for r in rows) / max(n, 1), 3),
        "independent_accuracy": round(sum(r["independent"] == r["expected"] for r in rows) / max(n, 1), 3),
        "agent_wrong": len(wrong),
        "agent_wrong_flagged": sum(r["status"] == "REJECTED" for r in wrong),
        "verified_but_wrong": sum(r["status"] == "VERIFIED" and r["agent"] != r["expected"] for r in rows),
        "claims_total": sum(sum(r["counts"].values()) for r in rows),
        "claims_blocked": sum(r["counts"]["BLOCKED"] for r in rows),
        "claims_uncorroborated": sum(r["counts"]["UNCORROBORATED"] for r in rows),
    }


def run_agent_bench(n: int = 18, seed: int = 3) -> dict:
    """Run (or replay cached) investigations on `n` blind cases and score them. Live runs are cached."""
    combos = [(clip_id, story) for clip_id in load_manifest()["clips"] for story in STORIES]
    random.Random(seed).shuffle(combos)
    rows = []
    for i, (clip_id, story) in enumerate(combos[:n]):
        case_seed = SEED_BASE + i
        case_id = f"{clip_id}-car-s{case_seed:04d}"
        case_dir = BENCH_DIR / "cases" / case_id
        if not case_dir.exists():
            try:
                generate_case(
                    clip_timing(clip_id), CAR, story, case_seed, BENCH_DIR / "cases", BENCH_DIR / "ground_truth"
                )
            except GenerationError as exc:
                log.info("skipped %s/%s: %s", clip_id, story, exc)
                continue
        case = build_case_store(case_dir)
        run = agent_run(case_id, clip_id, case.store, case.profile, live=False, cache_dir=CACHE / "agent_bench")
        _, _, counts, verdict = check_run(run, case.store)
        rows.append(
            {
                "case": case_id,
                "expected": EXPECTED[story],
                "agent": run["verdict"],
                "independent": verdict["independent_label"],
                "status": verdict["status"],
                "counts": counts,
            }
        )
        log.info("%s %s agent=%s %s %s", case_id, story, run["verdict"], verdict["status"], counts)
    result = {"summary": summarize(rows), "rows": rows}
    (ROOT / "agent_bench.json").write_text(json.dumps(result, indent=2))
    return result
