"""Lateral motion of a tracked vehicle relative to the ego lane.

Lane position is measured as `u`, the bottom-centre of the box expressed in lane widths at that vehicle's
own depth: 0 is the left lane edge, 1 the right edge, 0.5 dead centre, and values outside [0, 1] are
outside the lane. Working in lane widths rather than pixels cancels perspective, so the same thresholds
hold for a vehicle 10 m away and one 60 m away.

A lane change is then sustained lateral motion — the image-space form of "the car is angled across the
lane" — and time-to-lane-crossing is how long until a vehicle outside the lane reaches its edge at the
current rate, which is when a cut-in becomes *predictable* rather than when it becomes a fact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from telltale.video.lane import _lane_edges, _x_at
from telltale.video.trend import windowed_slope

MIN_RATE = 0.10
CONTINUE_FRACTION = 0.5
MIN_LANE_FRACTION = 0.15
MIN_NET_U = 0.15
MIN_FRAMES = 5


@dataclass(frozen=True)
class LaneChange:
    start_t: float
    end_t: float
    delta_u: float
    direction: str
    peak_rate: float


def lateral_offsets(dets: list[dict], poly_px: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    """Per-frame lane position `u` of each box's bottom-centre, in lane widths.

    Frames where the vehicle sits close to the point where the lane edges converge are dropped: the lane
    is a few pixels wide there, so dividing by its width turns ordinary box jitter into enormous offsets
    (one object on cand36 reached u = 5798 before this guard).
    """
    left, right = _lane_edges(poly_px)
    near_y = max(p[1] for p in poly_px)
    min_width = MIN_LANE_FRACTION * (_x_at(right, near_y) - _x_at(left, near_y))
    frames, offsets = [], []
    for d in dets:
        bottom = d["box"][3]
        x_left, x_right = _x_at(left, bottom), _x_at(right, bottom)
        if x_right - x_left < min_width:
            continue
        frames.append(d["frame"])
        offsets.append(((d["box"][0] + d["box"][2]) / 2 - x_left) / (x_right - x_left))
    return np.array(frames, dtype=float), np.array(offsets, dtype=float)


def lateral_rate(frames: np.ndarray, offsets: np.ndarray, fps: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rate of lane-width change per second, with the fitted offset and a significance flag."""
    return windowed_slope(frames / fps, offsets)


def lane_change_events(
    dets: list[dict],
    fps: float,
    poly_px: list[tuple[float, float]],
    min_rate: float = MIN_RATE,
    min_net_u: float = MIN_NET_U,
    min_frames: int = MIN_FRAMES,
) -> list[LaneChange]:
    """Maximal runs of significant, sustained sideways motion in one direction.

    `min_net_u` keeps slow drift and residual jitter out: a shift of 0.15 lane widths is roughly half a
    metre on a 3.5 m lane, below which calling something a lane change is not defensible.
    """
    frames, offsets = lateral_offsets(dets, poly_px)
    if len(frames) < min_frames:
        return []
    rate, fitted, significant = lateral_rate(frames, offsets, fps)
    starts = significant & (np.abs(rate) >= min_rate)
    # Hysteresis: a manoeuvre that momentarily eases off is still one manoeuvre, so continuing needs only
    # half the rate and no significance test. Requiring significance throughout split cand38's first lane
    # change into three fragments, each too small to report, at the frames where its rate dipped.
    continues = np.abs(rate) >= min_rate * CONTINUE_FRACTION

    events: list[LaneChange] = []
    i, n = 0, len(frames)
    while i < n:
        if not starts[i]:
            i += 1
            continue
        way = np.sign(rate[i])
        end = i
        while end + 1 < n and continues[end + 1] and np.sign(rate[end + 1]) == way:
            end += 1
        delta = float(fitted[end] - fitted[i])
        if end - i + 1 >= min_frames and abs(delta) >= min_net_u:
            run = rate[i : end + 1]
            events.append(
                LaneChange(
                    start_t=float(frames[i] / fps),
                    end_t=float(frames[end] / fps),
                    delta_u=delta,
                    direction="left" if delta < 0 else "right",
                    peak_rate=float(run[np.argmax(np.abs(run))]),
                )
            )
        i = end + 1
    return events


def time_to_lane_crossing(u: float, rate: float) -> float:
    """Seconds until a vehicle outside the lane reaches the near edge at the current rate."""
    if u > 1.0 and rate < 0:
        return (u - 1.0) / -rate
    if u < 0.0 and rate > 0:
        return -u / rate
    return math.inf
