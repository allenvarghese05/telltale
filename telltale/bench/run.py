"""Synthetic attribution benchmark: generate blind fault-injected cases, then score what the engine recovers."""

from __future__ import annotations

import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from telltale.config import CACHE, ROOT
from telltale.evidence.build import build_store
from telltale.logs.generate import EXPECTED, STORIES, ClipTiming, GenerationError, generate_case
from telltale.physics.profiles import PROFILES


def _clip_timings():
    from telltale.core.manifest import load_manifest
    from telltale.video.facts import compute_video_facts  # available after track A merges

    out = []
    for cid, clip in load_manifest()["clips"].items():
        p = CACHE / "sam" / f"{cid}.json"
        if p.exists():
            vf = compute_video_facts(json.loads(p.read_text()), clip)
            out.append((ClipTiming(cid, vf.lane_entry_t, vf.impact_t), vf))
    return out


def run_benchmark(n_seeds: int = 4, profiles=("car", "truck"), timings=None, out: Path | None = None) -> dict:
    """Score the deterministic engine against the hidden stories. Cases live in a temp dir and are discarded."""
    timings = timings if timings is not None else _clip_timings()
    rows, skipped = [], 0
    with tempfile.TemporaryDirectory() as td:
        for timing, vf in timings:
            for pname in profiles:
                for si, story in enumerate(STORIES):
                    for s in range(n_seeds):
                        seed = 1000 * (si + 1) + s
                        try:
                            cid = generate_case(timing, PROFILES[pname], story, seed, Path(td) / "c", Path(td) / "g")
                        except GenerationError:
                            skipped += 1
                            continue
                        pred = build_store(Path(td) / "c" / cid, vf, PROFILES[pname]).get("ATTR:label").value
                        rows.append(
                            {
                                "case": cid,
                                "profile": pname,
                                "story": story,
                                "expected": EXPECTED[story],
                                "predicted": pred,
                            }
                        )
    per = defaultdict(list)
    for r in rows:
        per[r["story"]].append(r["expected"] == r["predicted"])
    summary = {
        "n": len(rows),
        "skipped": skipped,
        "accuracy": sum(r["expected"] == r["predicted"] for r in rows) / max(len(rows), 1),
        "per_story": {k: sum(v) / len(v) for k, v in per.items()},
        "confusion": dict(Counter(f"{r['expected']}->{r['predicted']}" for r in rows)),
        "abstention_correct": sum(per["dropout"]) / max(len(per["dropout"]), 1),
        "false_inconclusive": sum(r["predicted"] == "INCONCLUSIVE" and r["story"] != "dropout" for r in rows),
    }
    result = {"summary": summary, "rows": rows}
    (out or ROOT / "bench_results.json").write_text(json.dumps(result, indent=2))
    return result
