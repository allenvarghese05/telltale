# Telltale — 02 Track B: Vehicle Logs, Physics, Evidence Store

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Work only in worktree `../telltale-b` (branch `track-b`). Allowed folders: `telltale/physics/`, `telltale/logs/`, `telltale/evidence/build.py`, `telltale/evidence/align.py`, `telltale/bench/`, `tests/physics/`, `tests/logs/`, `tests/evidence/`. **Do not import from `telltale.video`.** You only get `VideoFacts` from `telltale.core.schema`.

**Goal:**
- Vehicle profiles (car, truck), a longitudinal crash simulator, a counterfactual, and deterministic attribution.
- Realistic CAN (DBC-encoded) and ADAS (MCAP) log writers and parsers.
- A blind fault-injecting generator whose logs agree with what the video shows.
- Clock alignment, the evidence store builder, and the benchmark.

**Key idea (read before coding):** time zero for the physics is the video's lane-entry moment. The generator solves for the gap at lane entry so that simulated contact happens exactly at the video's impact time, so every generated log agrees with the footage. Faults change only things video cannot see: when the system perceived, when it commanded, and how fast pressure built.

---

### Task B1: Vehicle profiles and the crash simulator

**Files:**
- Create: `telltale/physics/profiles.py`, `telltale/physics/sim.py`
- Test: `tests/physics/test_sim.py`

- [ ] **Step 1: Write the failing test `tests/physics/test_sim.py`**

```python
import pytest

from telltale.physics.profiles import CAR, PROFILES, TRUCK
from telltale.physics.sim import BrakeModel, pressure_reached_time, simulate


def test_no_braking_contact_time_is_gap_over_closing_speed():
    r = simulate(25.0, 15.0, 10.0, t_request=99.0, brake=BrakeModel(8.0, 0.15), t_end=3.0)
    assert r.contact and r.contact_t == pytest.approx(1.0, abs=0.005)
    assert r.impact_rel_speed == pytest.approx(10.0, abs=0.05)


def test_early_hard_braking_avoids_contact():
    r = simulate(20.0, 15.0, 10.0, t_request=0.0, brake=BrakeModel(8.0, 0.15), t_end=5.0)
    assert not r.contact and r.min_gap > 0


def test_pressure_reached_time_first_order():
    assert pressure_reached_time(1.0, 0.15) == pytest.approx(1.1374, abs=1e-3)


def test_nominal_actuation_is_within_profile_threshold():
    for p in (CAR, TRUCK):
        lat = pressure_reached_time(0.0, p.tau_nominal)
        assert lat < p.thresholds["actuation_s"]
    assert set(PROFILES) == {"car", "truck"}
```

- [ ] **Step 2: Run it and confirm it fails.** `pytest tests/physics/test_sim.py -v` → FAIL.

- [ ] **Step 3: Write `telltale/physics/profiles.py`**

```python
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
```

- [ ] **Step 4: Write `telltale/physics/sim.py`**

```python
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
    n = int(round(t_end / dt)) + 1
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
    return t_request + tau * math.log(1.0 / (1.0 - frac))
```

- [ ] **Step 5: Run the tests and confirm they pass.** `pytest tests/physics/test_sim.py -v` → 4 passed.

- [ ] **Step 6: Commit.** `git add telltale/physics tests/physics && git commit -m "feat(physics): vehicle profiles and longitudinal crash simulator"`

---

### Task B2: Counterfactual and deterministic attribution

**Files:**
- Create: `telltale/physics/counterfactual.py`, `telltale/physics/attribution.py`
- Test: `tests/physics/test_attribution.py`

- [ ] **Step 1: Write the failing test `tests/physics/test_attribution.py`**

```python
from telltale.physics.attribution import Measured, attribute
from telltale.physics.counterfactual import counterfactual
from telltale.physics.profiles import CAR


def m(**kw):
    base = dict(
        perception_latency=0.2,
        command_latency=0.05,
        actuation_latency=0.14,
        handoff_margin=None,
        cf_nominal_contact=False,
        data_complete=True,
    )
    base.update(kw)
    return Measured(**base)


def test_unavoidable_when_nominal_counterfactual_still_collides():
    v = attribute(m(perception_latency=1.3, cf_nominal_contact=True), CAR)
    assert v.label == "UNAVOIDABLE" and v.noncausal_faults == ["perception"]


def test_largest_excess_wins():
    assert attribute(m(perception_latency=1.35), CAR).label == "PERCEPTION_LATE"
    assert attribute(m(actuation_latency=0.6), CAR).label == "BRAKE_ACTUATION_LATE"
    assert attribute(m(command_latency=0.5), CAR).label == "COMMAND_LATE"
    assert attribute(m(command_latency=None, handoff_margin=0.8), CAR).label == "LATE_HANDOFF"


def test_incomplete_data_is_inconclusive():
    assert attribute(m(perception_latency=1.35, data_complete=False), CAR).label == "INCONCLUSIVE"


def test_no_fault_found():
    assert attribute(m(), CAR).label == "NO_FAULT_FOUND"


def test_counterfactual_uses_nominal_latencies():
    r = counterfactual(25.0, 15.0, 30.0, CAR)
    assert not r.contact
    r2 = counterfactual(25.0, 15.0, 30.0, CAR, perception_s=2.9)
    assert r2.contact
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/physics/counterfactual.py`**

```python
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
    p = profile.nominal["perception_s"] if perception_s is None else perception_s
    c = profile.nominal["command_s"] if command_s is None else command_s
    k = profile.tau_nominal if tau is None else tau
    return simulate(v_ego0, v_other, d0, p + c, BrakeModel(profile.a_max, max(k, 0.01)), t_end=t_end)
```

- [ ] **Step 4: Write `telltale/physics/attribution.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field

LAYER_LABEL = {
    "perception": "PERCEPTION_LATE",
    "command": "COMMAND_LATE",
    "actuation": "BRAKE_ACTUATION_LATE",
    "handoff": "LATE_HANDOFF",
}


@dataclass
class Measured:
    perception_latency: float | None
    command_latency: float | None
    actuation_latency: float | None
    handoff_margin: float | None
    cf_nominal_contact: bool | None
    data_complete: bool = True


@dataclass
class Verdict:
    label: str
    excess: dict
    noncausal_faults: list = field(default_factory=list)


def attribute(m: Measured, profile) -> Verdict:
    thr = profile.thresholds
    excess: dict[str, float] = {}
    if m.perception_latency is not None:
        excess["perception"] = m.perception_latency - thr["perception_s"]
    if m.command_latency is not None:
        excess["command"] = m.command_latency - thr["command_s"]
    if m.actuation_latency is not None:
        excess["actuation"] = m.actuation_latency - thr["actuation_s"]
    if m.handoff_margin is not None:
        excess["handoff"] = thr["human_prt_s"] - m.handoff_margin
    faults = [k for k, v in excess.items() if v > 0]
    if not m.data_complete or m.cf_nominal_contact is None:
        return Verdict("INCONCLUSIVE", excess)
    if m.cf_nominal_contact:
        return Verdict("UNAVOIDABLE", excess, faults)
    if not faults:
        return Verdict("NO_FAULT_FOUND", excess)
    return Verdict(LAYER_LABEL[max(faults, key=lambda k: excess[k])], excess)
```

- [ ] **Step 5: Run the tests and confirm they pass.** `pytest tests/physics -v`

- [ ] **Step 6: Commit.** `git add telltale/physics tests/physics && git commit -m "feat(physics): counterfactual and but-for attribution"`

---

### Task B3: DBC files and CAN log I/O

**Files:**
- Create: `telltale/logs/dbc/car.dbc`, `telltale/logs/dbc/truck.dbc`, `telltale/logs/can_io.py`
- Test: `tests/logs/test_can_io.py`

- [ ] **Step 1: Write `telltale/logs/dbc/car.dbc`**

```
VERSION ""


NS_ :

BS_:

BU_: ECU


BO_ 256 VEH_SPEED: 8 ECU
 SG_ speed_mps : 0|16@1+ (0.01,0) [0|655.35] "m/s" Vector__XXX

BO_ 257 BRAKE: 8 ECU
 SG_ brake_request : 0|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ brake_pressure_kpa : 8|16@1+ (1,0) [0|65535] "kPa" Vector__XXX

BO_ 258 EDR_EVENT: 8 ECU
 SG_ impact : 0|1@1+ (1,0) [0|1] "" Vector__XXX
```

- [ ] **Step 2: Write `telltale/logs/dbc/truck.dbc`.** These are J1939-style 29-bit IDs; the DBC adds bit 31 to mark extended frames. The layout is simplified: real J1939 spreads these signals across CCVS1, XBR, EBC1 and AIR1.

```
VERSION ""


NS_ :

BS_:

BU_: ECU


BO_ 2566844672 CCVS1: 8 ECU
 SG_ speed_mps : 0|16@1+ (0.01,0) [0|655.35] "m/s" Vector__XXX

BO_ 2565865739 EBC_SIM: 8 ECU
 SG_ brake_request : 0|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ brake_pressure_kpa : 8|16@1+ (1,0) [0|65535] "kPa" Vector__XXX

BO_ 2566848512 EDR_EVENT: 8 ECU
 SG_ impact : 0|1@1+ (1,0) [0|1] "" Vector__XXX
```

- [ ] **Step 3: Write the failing test `tests/logs/test_can_io.py`**

```python
import pytest

from telltale.logs.can_io import decode_signals, load_dbc, message_for_signal, read_candump, write_candump


@pytest.mark.parametrize("dbc", ["car.dbc", "truck.dbc"])
def test_roundtrip(tmp_path, dbc):
    db = load_dbc(dbc)
    ms = message_for_signal(db, "speed_mps")
    mb = message_for_signal(db, "brake_request")
    frames = [
        (1700000000.0, ms.frame_id, ms.encode({"speed_mps": 25.37}), ms.is_extended_frame),
        (1700000000.02, mb.frame_id, mb.encode({"brake_request": 1, "brake_pressure_kpa": 410}), mb.is_extended_frame),
    ]
    p = tmp_path / "x.log"
    write_candump(p, frames)
    sig = decode_signals(read_candump(p), db)
    assert sig["speed_mps"][1][0] == pytest.approx(25.37, abs=0.01)
    assert sig["brake_pressure_kpa"][1][0] == 410
    assert sig["brake_request"][0][0] == pytest.approx(1700000000.02, abs=1e-6)


def test_truck_ids_are_extended():
    assert message_for_signal(load_dbc("truck.dbc"), "speed_mps").is_extended_frame
```

- [ ] **Step 4: Run it and confirm it fails.**

- [ ] **Step 5: Write `telltale/logs/can_io.py`**

```python
import re
from pathlib import Path

import cantools

from telltale.config import DBC_DIR

LINE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")


def load_dbc(name: str):
    return cantools.database.load_file(str(DBC_DIR / name))


def message_for_signal(db, signal: str):
    for m in db.messages:
        if any(s.name == signal for s in m.signals):
            return m
    raise KeyError(signal)


def write_candump(path, frames) -> None:
    """frames: iterable of (timestamp_s, frame_id, data_bytes, is_extended)."""
    lines = []
    for ts, fid, data, ext in sorted(frames, key=lambda f: f[0]):
        ident = f"{fid:08X}" if ext else f"{fid:03X}"
        lines.append(f"({ts:.6f}) can0 {ident}#{bytes(data).hex().upper()}")
    Path(path).write_text("\n".join(lines) + "\n")


def read_candump(path) -> list[tuple[float, int, bytes]]:
    out = []
    for line in Path(path).read_text().splitlines():
        m = LINE.match(line.strip())
        if m:
            out.append((float(m.group(1)), int(m.group(2), 16), bytes.fromhex(m.group(3))))
    return out


def decode_signals(frames, db) -> dict[str, tuple[list[float], list[float]]]:
    out: dict[str, tuple[list[float], list[float]]] = {}
    for ts, fid, data in frames:
        try:
            msg = db.get_message_by_frame_id(fid)
        except KeyError:
            continue
        for name, val in msg.decode(data).items():
            t, v = out.setdefault(name, ([], []))
            t.append(ts)
            v.append(float(val))
    return out
```

- [ ] **Step 6: Run the tests and confirm they pass.** `pytest tests/logs/test_can_io.py -v`

- [ ] **Step 7: Commit.** `git add telltale/logs tests/logs && git commit -m "feat(logs): DBC definitions and candump CAN I/O"`

---

### Task B4: ADAS MCAP I/O

**Files:**
- Create: `telltale/logs/mcap_io.py`
- Test: `tests/logs/test_mcap_io.py`

- [ ] **Step 1: Write the failing test**

```python
from telltale.logs.mcap_io import read_adas_mcap, write_adas_mcap


def test_mcap_roundtrip(tmp_path):
    p = tmp_path / "a.mcap"
    write_adas_mcap(
        p,
        [
            (
                "/adas/tracks",
                1_700_000_005_350_000_000,
                {"track_id": 7, "event": "first_seen", "range_m": 12.5, "rel_speed_mps": 9.0},
            ),
            ("/ego/speed", 1_700_000_000_000_000_000, {"speed_mps": 25.0}),
        ],
    )
    d = read_adas_mcap(p)
    assert d["/adas/tracks"][0][1]["range_m"] == 12.5
    assert abs(d["/adas/tracks"][0][0] - 1_700_000_005.35) < 1e-6
    assert d["/ego/speed"][0][1]["speed_mps"] == 25.0
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/logs/mcap_io.py`**

```python
import json

from mcap.reader import make_reader
from mcap.writer import Writer


def write_adas_mcap(path, messages) -> None:
    """messages: iterable of (topic, log_time_ns, payload_dict)."""
    with open(path, "wb") as f:
        w = Writer(f)
        w.start()
        sid = w.register_schema(name="telltale.Json", encoding="jsonschema", data=b'{"type":"object"}')
        channels: dict[str, int] = {}
        for topic, t_ns, payload in sorted(messages, key=lambda m: m[1]):
            if topic not in channels:
                channels[topic] = w.register_channel(topic=topic, message_encoding="json", schema_id=sid)
            w.add_message(
                channel_id=channels[topic],
                log_time=int(t_ns),
                publish_time=int(t_ns),
                data=json.dumps(payload).encode(),
            )
        w.finish()


def read_adas_mcap(path) -> dict[str, list[tuple[float, dict]]]:
    out: dict[str, list[tuple[float, dict]]] = {}
    with open(path, "rb") as f:
        for _schema, channel, message in make_reader(f).iter_messages():
            out.setdefault(channel.topic, []).append((message.log_time / 1e9, json.loads(message.data)))
    return out
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/logs -v`

- [ ] **Step 5: Commit.** `git add telltale/logs tests/logs && git commit -m "feat(logs): ADAS MCAP I/O"`

---

### Task B5: Blind fault-injecting log generator

**Files:**
- Create: `telltale/logs/generate.py`
- Test: `tests/logs/test_generate.py`

- [ ] **Step 1: Write the failing test `tests/logs/test_generate.py`**

```python
import json

import numpy as np
import pytest

from telltale.logs.generate import EXPECTED, ClipTiming, generate_case, sample_truth
from telltale.physics.profiles import CAR, TRUCK

TIMING = ClipTiming(clip_id="syn", lane_entry_t=4.0, impact_t=6.2)


@pytest.mark.parametrize("profile", [CAR, TRUCK])
@pytest.mark.parametrize("story", list(EXPECTED))
def test_truth_matches_requested_story_and_hits_video_impact(profile, story):
    t = sample_truth(TIMING, profile, story, np.random.default_rng(7))
    assert t.label == EXPECTED[story]
    assert abs(t.contact_t - (TIMING.impact_t - TIMING.lane_entry_t)) < 0.03


def test_case_files_hide_the_story(tmp_path):
    cid = generate_case(TIMING, CAR, "brake_slow", seed=3, out_root=tmp_path / "cases", gt_root=tmp_path / "gt")
    case = json.loads((tmp_path / "cases" / cid / "case.json").read_text())
    assert set(case) == {"case_id", "clip_id", "profile"}
    assert (tmp_path / "cases" / cid / "vehicle.can.log").exists()
    assert (tmp_path / "cases" / cid / "adas.mcap").exists()
    assert json.loads((tmp_path / "gt" / f"{cid}.json").read_text())["story"] == "brake_slow"
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/logs/generate.py`**

```python
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from telltale.logs.can_io import load_dbc, message_for_signal, write_candump
from telltale.logs.mcap_io import write_adas_mcap
from telltale.physics.attribution import Measured, attribute
from telltale.physics.counterfactual import counterfactual
from telltale.physics.sim import BrakeModel, pressure_reached_time, simulate

EPOCH0 = 1_700_000_000.0
CAN_HZ, AV_HZ = 50.0, 20.0
LOG_TAIL_S = 2.0
POST_IMPACT_DECEL = 12.0
EXPECTED = {
    "unavoidable": "UNAVOIDABLE",
    "perception_late": "PERCEPTION_LATE",
    "command_late": "COMMAND_LATE",
    "brake_slow": "BRAKE_ACTUATION_LATE",
    "late_handoff": "LATE_HANDOFF",
    "dropout": "INCONCLUSIVE",
}
STORIES = tuple(EXPECTED)


class GenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClipTiming:
    clip_id: str
    lane_entry_t: float
    impact_t: float


@dataclass
class Truth:
    story: str
    profile: str
    v_ego0: float
    v_other: float
    d0: float
    first_seen: float  # s after lane entry
    brake_request: float  # s after lane entry (ADAS, or driver for handoff)
    handoff: float | None  # s after lane entry
    tau: float
    contact_t: float
    can_skew: float
    av_skew: float
    label: str = ""


def solve_d0(v_ego0: float, v_other: float, t_req: float, brake: BrakeModel, t_imp: float) -> float:
    def ct(d0: float) -> float:
        r = simulate(v_ego0, v_other, d0, t_req, brake, t_end=t_imp + 2.0)
        return r.contact_t if r.contact else math.inf

    lo, hi = 0.05, (v_ego0 - v_other) * t_imp + 0.5
    if ct(lo) > t_imp or ct(hi) < t_imp:
        raise GenerationError("cannot bracket contact time")
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if ct(mid) <= t_imp:
            lo = mid
        else:
            hi = mid
    if abs(ct(lo) - t_imp) > 0.03:
        raise GenerationError("contact time not reachable with these speeds")
    return lo


def truth_label(t: Truth, profile, T: float) -> str:
    if t.story == "dropout":
        return "INCONCLUSIVE"
    m = Measured(
        perception_latency=t.first_seen,
        command_latency=None if t.handoff is not None else t.brake_request - t.first_seen,
        actuation_latency=pressure_reached_time(t.brake_request, t.tau) - t.brake_request,
        handoff_margin=None if t.handoff is None else T - t.handoff,
        cf_nominal_contact=counterfactual(t.v_ego0, t.v_other, t.d0, profile, t_end=T + 2.0).contact,
    )
    return attribute(m, profile).label


def sample_truth(timing: ClipTiming, profile, story: str, rng: np.random.Generator, max_attempts: int = 400) -> Truth:
    if story not in EXPECTED:
        raise ValueError(story)
    T = timing.impact_t - timing.lane_entry_t
    if T <= 0.3:
        raise GenerationError("impact too soon after lane entry")
    for _ in range(max_attempts):
        v_ego0 = float(rng.uniform(18.0, 30.0))
        dv = float(rng.uniform(3.0, min(16.0, v_ego0 - 2.0)))
        slow = story == "brake_slow"
        tau = profile.tau_nominal * float(rng.uniform(3.5, 5.0) if slow else rng.uniform(0.9, 1.1))
        first_seen = float(rng.uniform(1.0, 1.6) if story == "perception_late" else rng.uniform(0.10, 0.25))
        if first_seen >= T - 0.1:
            continue
        handoff = None
        if story == "late_handoff":
            handoff = T - float(rng.uniform(0.5, 1.1))
            if handoff <= first_seen + 0.05:
                continue
            t_req = handoff + float(rng.uniform(1.2, 1.6))  # human perception-reaction after handoff
        elif story == "command_late":
            t_req = first_seen + float(rng.uniform(0.6, 1.2))  # saw it in time; planner hesitated
        else:
            t_req = first_seen + float(rng.uniform(0.03, 0.08))
        brake = BrakeModel(profile.a_max, tau)
        try:
            d0 = solve_d0(v_ego0, v_ego0 - dv, t_req, brake, T)
        except GenerationError:
            continue
        contact = simulate(v_ego0, v_ego0 - dv, d0, t_req, brake, t_end=T + 2.0).contact_t
        truth = Truth(
            story,
            profile.name,
            v_ego0,
            v_ego0 - dv,
            d0,
            first_seen,
            t_req,
            handoff,
            tau,
            float(contact),
            float(rng.uniform(-0.5, 0.5)),
            float(rng.uniform(-0.8, 0.8)),
        )
        truth.label = truth_label(truth, profile, T)
        if truth.label == EXPECTED[story]:
            return truth
    raise GenerationError(f"no {story} parameters found for {timing}")


def _speed(rel: np.ndarray, sim, v0: float) -> np.ndarray:
    tc, vc = sim.contact_t, float(sim.v_ego[-1])
    out = np.empty_like(rel)
    for i, r in enumerate(rel):
        if r < 0:
            out[i] = v0
        elif r <= tc:
            out[i] = float(np.interp(r, sim.t, sim.v_ego))
        else:
            out[i] = max(vc - POST_IMPACT_DECEL * (r - tc), 0.0)
    return out


def _ns(tv: float, skew: float) -> int:
    return int(round((EPOCH0 + tv + skew) * 1e9))


def write_case(case_dir: Path, timing: ClipTiming, truth: Truth, profile) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    entry = timing.lane_entry_t
    sim = simulate(
        truth.v_ego0,
        truth.v_other,
        truth.d0,
        truth.brake_request,
        BrakeModel(profile.a_max, truth.tau),
        t_end=timing.impact_t - entry + LOG_TAIL_S,
    )
    t_end = timing.impact_t + LOG_TAIL_S

    tv = np.arange(0.0, t_end, 1.0 / CAN_HZ)
    rel = tv - entry
    speed = _speed(rel, sim, truth.v_ego0)
    since = np.clip(rel - truth.brake_request, 0.0, None)
    pressure = np.where(rel >= truth.brake_request, profile.p_max_kpa * (1.0 - np.exp(-since / truth.tau)), 0.0)
    req = (rel >= truth.brake_request).astype(int)

    db = load_dbc(profile.dbc)
    ms, mb, me = (message_for_signal(db, s) for s in ("speed_mps", "brake_request", "impact"))
    drop = (truth.brake_request - 0.2, truth.brake_request + 1.0) if truth.story == "dropout" else None
    frames = []
    for t_v, r, v, q, p in zip(tv, rel, speed, req, pressure):
        ts = EPOCH0 + t_v + truth.can_skew
        frames.append((ts, ms.frame_id, ms.encode({"speed_mps": round(float(v), 2)}), ms.is_extended_frame))
        if drop and drop[0] <= r <= drop[1]:
            continue
        frames.append(
            (
                ts + 0.001,
                mb.frame_id,
                mb.encode({"brake_request": int(q), "brake_pressure_kpa": int(round(float(p)))}),
                mb.is_extended_frame,
            )
        )
    frames.append(
        (EPOCH0 + entry + truth.contact_t + truth.can_skew, me.frame_id, me.encode({"impact": 1}), me.is_extended_frame)
    )
    write_candump(case_dir / "vehicle.can.log", frames)

    msgs = []
    av_tv = np.arange(0.0, t_end, 1.0 / AV_HZ)
    for t_v, v in zip(av_tv, _speed(av_tv - entry, sim, truth.v_ego0)):
        msgs.append(("/ego/speed", _ns(float(t_v), truth.av_skew), {"speed_mps": round(float(v), 3)}))
    dv = truth.v_ego0 - truth.v_other
    msgs.append(
        (
            "/adas/tracks",
            _ns(entry + truth.first_seen, truth.av_skew),
            {
                "track_id": 7,
                "event": "first_seen",
                "range_m": round(truth.d0 - dv * truth.first_seen, 3),
                "rel_speed_mps": round(dv, 3),
            },
        )
    )
    if truth.handoff is None:
        msgs.append(("/adas/events", _ns(entry + truth.brake_request, truth.av_skew), {"event": "brake_request"}))
    else:
        msgs.append(("/adas/events", _ns(entry + truth.handoff, truth.av_skew), {"event": "handoff"}))
    write_adas_mcap(case_dir / "adas.mcap", msgs)


def generate_case(timing: ClipTiming, profile, story: str, seed: int, out_root, gt_root) -> str:
    """Seeds must be unique per (clip, profile): the case id contains only the seed, never the story."""
    truth = sample_truth(timing, profile, story, np.random.default_rng(seed))
    case_id = f"{timing.clip_id}-{profile.name}-s{seed:04d}"
    case_dir = Path(out_root) / case_id
    write_case(case_dir, timing, truth, profile)
    (case_dir / "case.json").write_text(
        json.dumps({"case_id": case_id, "clip_id": timing.clip_id, "profile": profile.name})
    )
    gt = Path(gt_root)
    gt.mkdir(parents=True, exist_ok=True)
    (gt / f"{case_id}.json").write_text(json.dumps({**asdict(truth), "expected_label": EXPECTED[story]}, indent=2))
    return case_id
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/logs/test_generate.py -v`. If a parametrized story raises `GenerationError` for `TIMING`, widen that story's sampling ranges. Don't loosen the label check.

- [ ] **Step 5: Commit.** `git add telltale/logs tests/logs && git commit -m "feat(logs): blind fault-injecting generator consistent with video timing"`

---

### Task B6: Clock alignment

**Files:**
- Create: `telltale/evidence/align.py`
- Test: `tests/evidence/test_align.py`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
import pytest

from telltale.evidence.align import align_by_speed, can_offset_from_impact


def _speed(t):
    return np.where(t < 5.0, 25.0, np.maximum(25.0 - 12.0 * (t - 5.0), 0.0))


def test_can_offset_from_impact():
    assert can_offset_from_impact(8.0, 1_700_000_008.37) == pytest.approx(-1_700_000_000.37)


def test_align_by_speed_recovers_skew():
    ref_t = np.arange(0, 10, 0.02)
    true_offset = -0.37
    other_t = np.arange(0, 10, 0.05) - true_offset
    other_v = _speed(other_t + true_offset)
    off = align_by_speed(ref_t, _speed(ref_t), other_t, other_v, guess=0.0)
    assert off == pytest.approx(true_offset, abs=0.01)
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/evidence/align.py`**

```python
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
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/evidence/test_align.py -v`

- [ ] **Step 5: Commit.** `git add telltale/evidence/align.py tests/evidence && git commit -m "feat(evidence): impact and speed-trace clock alignment"`

---

### Task B7: Evidence store builder (the end-to-end deterministic engine)

**Files:**
- Create: `telltale/evidence/build.py`
- Test: `tests/evidence/test_build.py`

- [ ] **Step 1: Write the failing test `tests/evidence/test_build.py`**

```python
import pytest

from telltale.core.schema import Fact, VideoFacts
from telltale.evidence.build import build_store
from telltale.logs.generate import EXPECTED, ClipTiming, generate_case
from telltale.physics.profiles import PROFILES

TIMING = ClipTiming(clip_id="syn", lane_entry_t=4.0, impact_t=6.2)
VIDEO = VideoFacts("syn", 30.0, 4.0, 6.2, 1.9, "1")


@pytest.mark.parametrize("profile", ["car", "truck"])
@pytest.mark.parametrize("story", list(EXPECTED))
def test_engine_recovers_the_injected_story_blind(tmp_path, profile, story):
    cid = generate_case(TIMING, PROFILES[profile], story, seed=11, out_root=tmp_path / "c", gt_root=tmp_path / "g")
    store = build_store(tmp_path / "c" / cid, VIDEO, PROFILES[profile])
    assert store.get("ATTR:label").value == EXPECTED[story]
    assert store.verify_integrity()


def test_store_contains_core_facts_and_extra_witness_facts(tmp_path):
    cid = generate_case(
        TIMING, PROFILES["car"], "perception_late", seed=5, out_root=tmp_path / "c", gt_root=tmp_path / "g"
    )
    wit = [Fact("WIT:other_vehicle_turn_signal", "no", "", "WIT", "spark", "observation")]
    s = build_store(tmp_path / "c" / cid, VIDEO, PROFILES["car"], extra_facts=wit)
    for fid in [
        "VID:lane_entry_t",
        "AV:first_seen_t",
        "CAN:brake_request_t",
        "PHYS:perception_latency_s",
        "PHYS:cf_nominal_contact",
        "PROFILE:perception_threshold_s",
        "DATA:brake_log_complete",
        "WIT:other_vehicle_turn_signal",
        "PHYS:gap_at_entry_m",
        "CAN:speed_at_entry_mps",
    ]:
        assert s.has(fid), fid
    assert s.get("PHYS:perception_latency_s").value > 0.9
    assert "can.speed_mps" in s.series_names()
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/evidence/build.py`**

```python
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from telltale.core.schema import Fact, VideoFacts
from telltale.evidence.align import align_by_speed, can_offset_from_impact
from telltale.evidence.store import EvidenceStore
from telltale.logs.can_io import decode_signals, load_dbc, read_candump
from telltale.logs.mcap_io import read_adas_mcap
from telltale.physics.attribution import Measured, attribute
from telltale.physics.counterfactual import counterfactual
from telltale.physics.sim import BrakeModel, simulate

PRESSURE_FRAC = 0.6
MAX_BRAKE_GAP_S = 0.1


def _first(ts, vs, pred, after: float = -math.inf) -> float | None:
    for t, v in zip(ts, vs):
        if t >= after and pred(v):
            return float(t)
    return None


def build_store(case_dir, video: VideoFacts, profile, extra_facts: list[Fact] | None = None) -> EvidenceStore:
    case_dir = Path(case_dir)
    sig = decode_signals(read_candump(case_dir / "vehicle.can.log"), load_dbc(profile.dbc))
    impact_ts = _first(*sig["impact"], lambda v: v >= 1)
    if impact_ts is None:
        raise ValueError("CAN log has no EDR impact trigger")
    can_off = can_offset_from_impact(video.impact_t, impact_ts)

    def tv(name):
        t, v = sig[name]
        return np.asarray(t) + can_off, np.asarray(v)

    spd_t, spd_v = tv("speed_mps")
    req_t, req_v = tv("brake_request")
    prs_t, prs_v = tv("brake_pressure_kpa")

    av = read_adas_mcap(case_dir / "adas.mcap")
    av_t = np.array([t for t, _ in av["/ego/speed"]])
    av_v = np.array([m["speed_mps"] for _, m in av["/ego/speed"]])
    av_off = align_by_speed(spd_t, spd_v, av_t, av_v, guess=can_off)
    track_t, track = av["/adas/tracks"][0]
    first_seen = track_t + av_off
    events = {m["event"]: t + av_off for t, m in av.get("/adas/events", [])}

    can_req = _first(req_t, req_v, lambda v: v >= 1)
    reached = (
        None
        if can_req is None
        else _first(prs_t, prs_v, lambda v: v >= PRESSURE_FRAC * profile.p_max_kpa, after=can_req)
    )
    w0, w1 = first_seen, video.impact_t + 0.5
    inside = np.sort(prs_t[(prs_t >= w0) & (prs_t <= w1)])
    max_gap = float(np.max(np.diff(np.concatenate(([w0], inside, [w1])))))
    complete = max_gap <= MAX_BRAKE_GAP_S

    entry = video.lane_entry_t
    handoff = events.get("handoff")
    perception = first_seen - entry
    command = None if handoff is not None or "brake_request" not in events else events["brake_request"] - first_seen
    actuation = None if can_req is None or reached is None else reached - can_req
    margin = None if handoff is None else video.impact_t - handoff

    v0 = float(np.interp(entry, spd_t, spd_v))
    dv = float(track["rel_speed_mps"])
    d0 = float(track["range_m"]) + dv * (first_seen - entry)
    t_end = video.impact_t - entry + 2.0
    cf = counterfactual(v0, v0 - dv, d0, profile, t_end=t_end)
    tau_est = None if actuation is None else max(actuation / math.log(1 / (1 - PRESSURE_FRAC)), 0.01)
    actual_speed = None
    if can_req is not None and tau_est is not None:
        actual_speed = simulate(
            v0, v0 - dv, d0, can_req - entry, BrakeModel(profile.a_max, tau_est), t_end=t_end
        ).impact_rel_speed
    verdict = attribute(Measured(perception, command, actuation, margin, cf.contact, complete), profile)

    facts: list[Fact] = []

    def add(fid, value, unit, src, how, kind="measurement"):
        if value is None:
            return
        if isinstance(value, float):
            value = round(value, 4)
        facts.append(Fact(fid, value, unit, src, how, kind))

    add(
        "VID:lane_entry_t",
        entry,
        "s",
        "VID",
        f"SAM 3.1 object {video.target_object_id} box bottom-centre entered ego-lane polygon",
    )
    add("VID:impact_t", video.impact_t, "s", "VID", "Nexar dataset time_of_event label")
    add("VID:ttc_at_entry_s", video.ttc_at_entry, "s", "VID", "box width / d(width)/dt at lane entry")
    add("VID:target_object_id", video.target_object_id, "", "VID", "largest tracked vehicle at impact frame")
    add("CAN:clock_offset_s", can_off, "s", "CAN", "EDR impact trigger aligned to video impact")
    add("AV:clock_offset_s", av_off, "s", "AV", "ADAS ego-speed trace aligned to CAN speed (MSE grid search)")
    add("AV:first_seen_t", first_seen, "s", "AV", "first /adas/tracks message for the cut-in vehicle")
    add("AV:brake_request_t", events.get("brake_request"), "s", "AV", "/adas/events brake_request")
    add("AV:handoff_t", handoff, "s", "AV", "/adas/events handoff to driver")
    add("AV:range_at_first_seen_m", float(track["range_m"]), "m", "AV", "radar range at first detection")
    add("AV:rel_speed_mps", dv, "m/s", "AV", "radar closing speed at first detection")
    add("CAN:brake_request_t", can_req, "s", "CAN", "first brake_request=1 frame")
    add(
        "CAN:pressure_reached_t",
        reached,
        "s",
        "CAN",
        f"brake pressure first >= {int(PRESSURE_FRAC * 100)}% of full application",
    )
    add("CAN:speed_at_entry_mps", v0, "m/s", "CAN", "CAN wheel speed interpolated at lane entry")
    add("PHYS:perception_latency_s", perception, "s", "PHYS", "AV:first_seen_t - VID:lane_entry_t", "derived")
    add("PHYS:command_latency_s", command, "s", "PHYS", "AV:brake_request_t - AV:first_seen_t", "derived")
    add("PHYS:actuation_latency_s", actuation, "s", "PHYS", "CAN:pressure_reached_t - CAN:brake_request_t", "derived")
    add("PHYS:handoff_margin_s", margin, "s", "PHYS", "VID:impact_t - AV:handoff_t", "derived")
    add("PHYS:brake_tau_est_s", tau_est, "s", "PHYS", "first-order time constant from actuation latency", "derived")
    add("PHYS:gap_at_entry_m", d0, "m", "PHYS", "radar range back-propagated to lane entry", "derived")
    add("PHYS:actual_impact_speed_mps", actual_speed, "m/s", "PHYS", "replay with measured timings", "derived")
    add(
        "PHYS:cf_nominal_contact",
        bool(cf.contact),
        "",
        "PHYS",
        "counterfactual with nominal perception/command/actuation",
        "derived",
    )
    add("PHYS:cf_nominal_min_gap_m", cf.min_gap, "m", "PHYS", "counterfactual closest gap", "derived")
    add(
        "PHYS:cf_nominal_impact_speed_mps", cf.impact_rel_speed, "m/s", "PHYS", "counterfactual impact speed", "derived"
    )
    for k, name in (
        ("perception_s", "perception"),
        ("command_s", "command"),
        ("actuation_s", "actuation"),
        ("human_prt_s", "human_prt"),
    ):
        add(
            f"PROFILE:{name}_threshold_s" if name != "human_prt" else "PROFILE:human_prt_s",
            profile.thresholds[k],
            "s",
            "PROFILE",
            f"{profile.name} profile tolerance",
        )
    add(
        "PROFILE:nominal_perception_s",
        profile.nominal["perception_s"],
        "s",
        "PROFILE",
        "nominal value for counterfactuals",
    )
    add("PROFILE:nominal_command_s", profile.nominal["command_s"], "s", "PROFILE", "nominal value for counterfactuals")
    add("PROFILE:nominal_tau_s", profile.tau_nominal, "s", "PROFILE", "nominal brake time constant for counterfactuals")
    add(
        "DATA:brake_log_complete",
        bool(complete),
        "",
        "DATA",
        f"no brake-frame gap > {MAX_BRAKE_GAP_S}s in decision window",
    )
    add("DATA:max_brake_gap_s", max_gap, "s", "DATA", "largest gap between brake frames in decision window")
    for k, v in verdict.excess.items():
        add(f"ATTR:excess_{k}_s", v, "s", "ATTR", f"measured {k} latency minus tolerance", "derived")
    add("ATTR:label", verdict.label, "", "ATTR", "deterministic but-for attribution", "derived")
    add(
        "ATTR:noncausal_faults",
        ",".join(verdict.noncausal_faults) or "none",
        "",
        "ATTR",
        "faults present but not causal",
        "derived",
    )
    facts.extend(extra_facts or [])

    series = {
        "can.speed_mps": {"t": spd_t.tolist(), "v": spd_v.tolist(), "unit": "m/s", "source": "CAN"},
        "can.brake_pressure_kpa": {"t": prs_t.tolist(), "v": prs_v.tolist(), "unit": "kPa", "source": "CAN"},
        "can.brake_request": {"t": req_t.tolist(), "v": req_v.tolist(), "unit": "", "source": "CAN"},
        "av.speed_mps": {"t": (av_t + av_off).tolist(), "v": av_v.tolist(), "unit": "m/s", "source": "AV"},
    }
    return EvidenceStore(facts, series)
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/evidence -v`. If a near-threshold case flips, check alignment accuracy first, using `AV:clock_offset_s` against the truth skews. Do not change thresholds to make tests pass.

- [ ] **Step 5: Commit.** `git add telltale/evidence tests/evidence && git commit -m "feat(evidence): store builder — alignment, latencies, counterfactual, attribution"`

---

### Task B8: Benchmark

**Files:**
- Create: `telltale/bench/run.py`
- Test: `tests/evidence/test_bench.py`

- [ ] **Step 1: Write the failing test**

```python
from telltale.bench.run import run_benchmark
from telltale.core.schema import VideoFacts
from telltale.logs.generate import ClipTiming


def test_benchmark_reports_accuracy_on_synthetic_timing(tmp_path):
    t = ClipTiming("syn", 4.0, 6.2)
    vf = VideoFacts("syn", 30.0, 4.0, 6.2, 1.9, "1")
    res = run_benchmark(n_seeds=1, timings=[(t, vf)], out=tmp_path / "bench.json")
    s = res["summary"]
    assert s["n"] == 12 and s["accuracy"] >= 0.8  # 2 profiles x 6 stories
    assert {"per_story", "confusion", "abstention_correct", "false_inconclusive"} <= set(s)
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/bench/run.py`**

```python
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
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/evidence/test_bench.py -v`

- [ ] **Step 5: Run the whole track suite.** `pytest tests/physics tests/logs tests/evidence -v` → all pass.

- [ ] **Step 6: Commit.** `git add telltale/bench tests/evidence && git commit -m "feat(bench): blind fault-injection benchmark"`
