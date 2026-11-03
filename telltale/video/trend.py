"""Robust trend estimation for noisy per-frame measurements from SAM boxes.

Both time-to-collision (box width) and lane change (lateral position) ask the same question of a noisy
series: is it really moving, and how fast? Measured on the demo clips, box dimensions jitter by ~10 px
frame to frame and SAM occasionally merges a box with its neighbour for a single frame. A pointwise
derivative turns both into confident nonsense, so the slope is fitted over a window and reported as
significant only when it exceeds its own standard error.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

MEDIAN_FRAMES = 5
FIT_FRAMES = 15
SIGNIFICANCE = 3.0
MAD_TO_SIGMA = 1.4826


def windowed_slope(
    times: np.ndarray,
    values: np.ndarray,
    median_frames: int = MEDIAN_FRAMES,
    fit_frames: int = FIT_FRAMES,
    significance: float = SIGNIFICANCE,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-frame (slope, fitted value, is-significant) from a least-squares fit over a sliding window.

    The series is median-filtered first, which deletes single-frame outliers instead of smearing them.
    The slope's standard error is measured against the *raw* values, because the median filter correlates
    its own residuals, and its scale is a median absolute deviation, so one outlier cannot inflate it.
    """
    values = np.asarray(values, dtype=float)
    times = np.asarray(times, dtype=float)
    n = len(values)
    slope = np.zeros(n)
    fitted = np.array(values, dtype=float)
    significant = np.zeros(n, dtype=bool)
    if n < fit_frames + 2:
        return slope, fitted, significant

    smoothed = median_filter(values, size=median_frames, mode="nearest")
    half = fit_frames // 2
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        t, v = times[lo:hi], smoothed[lo:hi]
        centred = t - t.mean()
        spread = float(np.sum(centred**2))
        if spread <= 0:
            continue
        gradient = float(np.sum(centred * (v - v.mean())) / spread)
        line = v.mean() + gradient * centred
        residuals = values[lo:hi] - line
        sigma = MAD_TO_SIGMA * float(np.median(np.abs(residuals - np.median(residuals))))
        slope[i] = gradient
        fitted[i] = v.mean() + gradient * (times[i] - t.mean())
        significant[i] = abs(gradient) > significance * (sigma / float(np.sqrt(spread)))
    return slope, fitted, significant
