"""1-D longitudinal crash simulator: ego closing on a constant-speed lead vehicle."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BrakeModel:
    a_max: float
    tau: float


@dataclass
class SimResult:
    contact: bool
    contact_t: float | None
    impact_rel_speed: float
    min_gap: float
    t: np.ndarray
    gap: np.ndarray
    v_ego: np.ndarray


def simulate(
    v_ego0: float, v_other: float, d0: float, t_request: float, brake: BrakeModel, t_end: float = 8.0, dt: float = 0.001
) -> SimResult:
    """1-D: ego starts d0 metres behind the other vehicle (constant speed); brakes from t_request."""
    n = round(t_end / dt) + 1
    t = np.arange(n) * dt
    since = np.clip(t - t_request, 0.0, None)
    a = np.where(t >= t_request, brake.a_max * (1.0 - np.exp(-since / brake.tau)), 0.0)
    v = np.maximum(v_ego0 - np.concatenate(([0.0], np.cumsum(a[:-1]) * dt)), 0.0)
    x_ego = np.concatenate(([0.0], np.cumsum(v[:-1]) * dt))
    gap = d0 + v_other * t - x_ego
    hit = np.nonzero(gap <= 0.0)[0]
    if hit.size:
        i = int(hit[0])
        return SimResult(
            True,
            float(t[i]),
            float(max(v[i] - v_other, 0.0)),
            float(gap[: i + 1].min()),
            t[: i + 1],
            gap[: i + 1],
            v[: i + 1],
        )
    return SimResult(False, None, 0.0, float(gap.min()), t, gap, v)


def pressure_reached_time(t_request: float, tau: float, frac: float = 0.6) -> float:
    """Time at which a first-order pressure build from t_request reaches `frac` of full application."""
    return t_request + tau * math.log(1.0 / (1.0 - frac))
