"""Clock alignment: every evidence time is expressed in video seconds, anchored off the video's own events."""

from __future__ import annotations

import numpy as np


def can_offset_from_impact(video_impact_t: float, can_impact_ts: float) -> float:
    """CAN is anchored to video by the EDR impact trigger: video_t = can_ts + offset."""
    return video_impact_t - can_impact_ts


def align_by_speed(ref_t, ref_v, other_t, other_v, guess: float, search: float = 1.5, step: float = 0.002) -> float:
    """ADAS log is anchored to CAN by matching its ego-speed trace to CAN speed (grid search, MSE)."""
    ref_t, ref_v = np.asarray(ref_t, float), np.asarray(ref_v, float)
    other_t, other_v = np.asarray(other_t, float), np.asarray(other_v, float)
    best = None
    for off in np.arange(guess - search, guess + search + step / 2, step):
        ot = other_t + off
        lo, hi = max(ref_t[0], ot[0]), min(ref_t[-1], ot[-1])
        if hi - lo < 1.0:
            continue
        grid = np.arange(lo, hi, 0.01)
        err = float(np.mean((np.interp(grid, ref_t, ref_v) - np.interp(grid, ot, other_v)) ** 2))
        if best is None or err < best[0]:
            best = (err, float(off))
    if best is None:
        raise ValueError("logs do not overlap in time")
    return best[1]
