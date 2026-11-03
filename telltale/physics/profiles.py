"""Vehicle profiles: braking capability, nominal latencies and the tolerances attribution judges against."""

from __future__ import annotations

from dataclasses import dataclass, field

NOMINAL = {"perception_s": 0.20, "command_s": 0.05}


@dataclass(frozen=True)
class VehicleProfile:
    name: str
    a_max: float  # m/s^2, maximum deceleration magnitude
    tau_nominal: float  # s, brake actuation first-order time constant
    p_max_kpa: float  # full-application brake pressure
    dbc: str
    thresholds: dict = field(default_factory=dict)
    nominal: dict = field(default_factory=lambda: dict(NOMINAL))


CAR = VehicleProfile(
    "car",
    a_max=8.0,
    tau_nominal=0.15,
    p_max_kpa=12000.0,
    dbc="car.dbc",
    thresholds={"perception_s": 0.30, "command_s": 0.10, "actuation_s": 0.25, "human_prt_s": 1.5},
)
# Class 8 air brakes: slower pressure build, lower deceleration (laden tractor-trailer).
TRUCK = VehicleProfile(
    "truck",
    a_max=4.5,
    tau_nominal=0.35,
    p_max_kpa=690.0,
    dbc="truck.dbc",
    thresholds={"perception_s": 0.30, "command_s": 0.10, "actuation_s": 0.45, "human_prt_s": 1.5},
)
PROFILES = {"car": CAR, "truck": TRUCK}
