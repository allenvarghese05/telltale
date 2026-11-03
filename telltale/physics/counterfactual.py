"""The but-for run: what the same crash geometry would have done with nominal system latencies."""

from __future__ import annotations

from telltale.physics.profiles import VehicleProfile
from telltale.physics.sim import BrakeModel, SimResult, simulate


def counterfactual(
    v_ego0: float,
    v_other: float,
    d0: float,
    profile: VehicleProfile,
    perception_s: float | None = None,
    command_s: float | None = None,
    tau: float | None = None,
    t_end: float = 10.0,
) -> SimResult:
    """Replay the encounter with nominal (or overridden) perception, command and actuation behaviour."""
    p = profile.nominal["perception_s"] if perception_s is None else perception_s
    c = profile.nominal["command_s"] if command_s is None else command_s
    k = profile.tau_nominal if tau is None else tau
    return simulate(v_ego0, v_other, d0, p + c, BrakeModel(profile.a_max, max(k, 0.01)), t_end=t_end)
