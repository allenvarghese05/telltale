"""Benchmark Telltale's automatic danger onset against Nexar's own human annotations.

Nexar's `time_of_alert`, from the dataset paper (arXiv:2503.03848), is "the earliest moment when a focused
human can recognize that a dangerous situation is about to occur" — Figure 1 and Table 2 phrase it as "the
earliest moment that the driver could intervene to prevent the accident". Each clip was annotated by several
people: the event time is the **median** of their answers, but the alert time is the **second-highest**
value, chosen over the median precisely because alert annotation is so subjective, which biases the label
toward shorter alert-to-accident intervals.

Two consequences for reading these numbers honestly:

- The label is a *human perceptual* onset, deliberately skewed late. Telltale's onset is geometric — a
  vehicle crossing into the ego lane, closing on its edge, or closing within it. A systematic signed offset
  between the two is expected and should be reported, not tuned away.
- These clips are scored with the **default** ego-lane polygon and no per-clip tuning of any kind. Nothing
  in this module's thresholds may ever be adjusted by looking at these results; that would turn the one
  independent measurement in the project into another piece of self-assessment.
"""

from __future__ import annotations

import json
import logging
import random
import statistics
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from telltale.config import BENCH_CLIPS, CACHE, ROOT
from telltale.core.manifest import BENCH_MANIFEST, load_manifest, save_manifest
from telltale.video.sam import run_sam
from telltale.video.scene import summarize_scene

logger = logging.getLogger(__name__)

POOL_EXCLUSIONS = BENCH_CLIPS / "pool_exclusions.json"


def summarize(rows: list[dict]) -> dict:
    """Describe the error distribution, not just how often it lands inside a tight band.

    The label is a human perceptual onset biased late, so a calibrated detector is expected to sit a
    consistent distance behind it. `within_0_5s` and `within_1_0s` would read near zero for such a
    detector and look like failure. The spread of the *signed* error is the honest measure: a tight
    spread means we are tracking the same moment as the annotator, whatever the constant offset.
    """
    ok = [r for r in rows if r.get("ok")]
    found = [r for r in ok if r.get("onset_t") is not None and r.get("alert_t") is not None]
    errs = [abs(r["onset_t"] - r["alert_t"]) for r in found]
    signed = [r["onset_t"] - r["alert_t"] for r in found]
    return {
        "n_attempted": len(rows),
        "n_target_found": len(ok),
        "n_onset_found": len(found),
        "onset_coverage": round(len(found) / len(rows), 3) if rows else None,
        "median_abs_err_s": round(statistics.median(errs), 3) if errs else None,
        "p25_abs_err_s": round(float(np.percentile(errs, 25)), 3) if errs else None,
        "p75_abs_err_s": round(float(np.percentile(errs, 75)), 3) if errs else None,
        "mean_signed_err_s": round(statistics.mean(signed), 3) if signed else None,
        "median_signed_err_s": round(statistics.median(signed), 3) if signed else None,
        "stdev_signed_err_s": round(statistics.stdev(signed), 3) if len(signed) >= 2 else None,
        "within_0_5s": round(sum(e <= 0.5 for e in errs) / len(errs), 3) if errs else None,
        "within_1_0s": round(sum(e <= 1.0 for e in errs) / len(errs), 3) if errs else None,
        "within_2_0s": round(sum(e <= 2.0 for e in errs) / len(errs), 3) if errs else None,
    }


def benchmark_pool(clips: list[dict], excluded: set[str], seed: int) -> list[dict]:
    """Every labelled positive not excluded, in the seeded order the benchmark draws from."""
    pool = [c for c in clips if c["nexar_id"] not in excluded and c.get("time_of_alert") is not None]
    random.Random(seed).shuffle(pool)
    return pool


def _excluded() -> set[str]:
    """The clips the benchmark must never draw: the frozen original exclusions plus today's demo clips.

    The first 40-clip run excluded the 64 demo candidates then in the manifest. The manifest now holds 4, and
    excluding only those reshuffles the whole pool, so the original 40 would no longer be a prefix of any draw.
    `pool_exclusions.json` freezes the original 64 so every run, at any n, draws from the same order.
    """
    if not POOL_EXCLUSIONS.exists():
        raise FileNotFoundError(f"{POOL_EXCLUSIONS} is missing; without it the benchmark draws a different pool")
    frozen = set(json.loads(POOL_EXCLUSIONS.read_text()))
    return frozen | {c["nexar_id"] for c in load_manifest()["clips"].values()}


def _fetch_pool(n: int, seed: int) -> tuple[dict, list[dict], list[str]]:
    """Download the first n clips of the draw; returns the bench manifest, the draw and any failed downloads."""
    from telltale.data.fetch import fetch_trimmed, positive_clips

    drawn = benchmark_pool(positive_clips(), _excluded(), seed)[:n]
    bench = load_manifest(BENCH_MANIFEST)
    failed = []
    for meta in drawn:
        if meta["nexar_id"] in bench["clips"]:
            continue
        try:
            bench["clips"][meta["nexar_id"]] = fetch_trimmed(meta, BENCH_CLIPS, meta["nexar_id"], delete_raw=True)
        except Exception as exc:  # noqa: BLE001 - one bad clip must not end the benchmark
            logger.warning("fetch failed for %s: %s", meta["nexar_id"], exc)
            failed.append(meta["nexar_id"])
    save_manifest(bench, BENCH_MANIFEST)
    return bench, drawn, failed


def _score(entry: dict) -> dict:
    out = CACHE / "sam_bench" / f"{entry['clip_id']}.json"
    try:
        if not out.exists():
            run_sam(BENCH_CLIPS / entry["file"], out, entry["fps"], entry["width"], entry["height"])
        scene = summarize_scene(json.loads(out.read_text()), entry)
        return {
            "nexar_id": entry["clip_id"],
            "ok": True,
            "onset_t": scene.danger_onset_t,
            "onset_reason": scene.danger_onset_reason,
            "first_hazard_t": scene.first_hazard_t,
            "alert_t": entry["time_of_alert"],
            "event_t": entry["time_of_event"],
        }
    except Exception as exc:  # noqa: BLE001 - record the failure and keep scoring the rest
        return {"nexar_id": entry["clip_id"], "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def run_video_bench(n: int = 40, seed: int = 7, workers: int = 4) -> dict:
    bench, drawn, fetch_failed = _fetch_pool(n, seed)
    entries = [bench["clips"][m["nexar_id"]] for m in drawn if m["nexar_id"] in bench["clips"]]
    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(_score, entries))
    result = {"summary": summarize(rows), "rows": rows, "fetch_failed": fetch_failed}
    (ROOT / "video_bench.json").write_text(json.dumps(result, indent=2))
    return result
