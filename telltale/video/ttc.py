"""Time-to-collision from the growth of the target's bounding box.

A vehicle's apparent width grows as it closes, so TTC ~= width / (d width / dt). Two properties of real
SAM output, measured on the demo clips, drive the implementation:

- SAM occasionally merges the target's box with a neighbour for a single frame (a 444 px spike on one
  frame of 284 in cand38). A mean filter smears such a spike across its window, so the width series is
  median-filtered first, which removes it outright.
- Box width jitters by ~10 px frame to frame, which is a large fraction of a distant target's width. A
  pointwise derivative turns that jitter into an apparent closing speed and reports TTC well under a
  second at the very start of every clip. The slope is therefore estimated by a least-squares fit over a
  window, and TTC is left infinite unless that slope is significantly larger than its own standard error
  — "is this growth real?" rather than a hand-picked pixel threshold.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

MEDIAN_FRAMES = 5
FIT_FRAMES = 15
SIGNIFICANCE = 3.0


def ttc_series(
    dets: list[dict],
    fps: float,
    median_frames: int = MEDIAN_FRAMES,
    fit_frames: int = FIT_FRAMES,
    dimension: str = "width",
) -> tuple[np.ndarray, np.ndarray]:
    """Time to collision from the growth of one box dimension.

    Height is the right choice for a vehicle beside or crossing the ego car: a box clipped at the frame edge stops
    widening while the vehicle is still closing, and a turning vehicle's width changes with its yaw, but its
    height changes only with distance.
    """
    if dimension not in ("width", "height"):
        raise ValueError(f"dimension must be 'width' or 'height', got {dimension!r}")
    lo_i, hi_i = (0, 2) if dimension == "width" else (1, 3)
    frames = np.array([d["frame"] for d in dets], dtype=float)
    width = np.array([d["box"][hi_i] - d["box"][lo_i] for d in dets], dtype=float)
    ttc = np.full(len(width), np.inf)
    if len(width) < fit_frames + 2:
        return frames, ttc

    smoothed = median_filter(width, size=median_frames, mode="nearest")
    times = frames / fps
    half = fit_frames // 2
    for i in range(len(width)):
        lo, hi = max(0, i - half), min(len(width), i + half + 1)
        t, w = times[lo:hi], smoothed[lo:hi]
        spread = float(np.sum((t - t.mean()) ** 2))
        if spread <= 0:
            continue
        slope = float(np.sum((t - t.mean()) * (w - w.mean())) / spread)
        if slope <= 0:
            continue
        fitted = w.mean() + slope * (times[i] - t.mean())
        # Noise is measured against the raw widths, because the median filter correlates its own residuals
        # and would understate the standard error. The scale is the median absolute deviation rather than
        # the root mean square, so a single merged-box frame inflates the slope's error bar by nothing.
        residuals = width[lo:hi] - (w.mean() + slope * (t - t.mean()))
        sigma = 1.4826 * float(np.median(np.abs(residuals - np.median(residuals))))
        slope_err = sigma / float(np.sqrt(spread))
        if slope > SIGNIFICANCE * slope_err and fitted > 0:
            ttc[i] = fitted / slope
    return frames, ttc


def ttc_at(frames: np.ndarray, ttc: np.ndarray, frame: int) -> float | None:
    if len(frames) == 0:
        return None
    value = float(ttc[int(np.argmin(np.abs(frames - frame)))])
    return value if np.isfinite(value) else None


def first_sustained_below(frames: np.ndarray, ttc: np.ndarray, threshold: float, hold: int = 3) -> int | None:
    below = np.isfinite(ttc) & (ttc < threshold)
    for i in range(len(below) - hold + 1):
        if below[i : i + hold].all():
            return int(frames[i])
    return None
