# Telltale Implementation Plan — 00 Overview, Interfaces, Task 0, Smoke Tests

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a real dashcam crash clip plus the vehicle's own logs into an independent, auditable causal verdict. Was it perception, the braking decision, the brake hardware, a late handoff, or physically unavoidable?

**Architecture: "Meta AI investigates, the checker verifies."**
- **Perception (Meta AI):** SAM 3.1 tracks the vehicles and timestamps lane entry; Muse Spark 1.3 watches the video as a witness.
- **Investigation (Meta AI):** a Muse Wonder agent reads the evidence. It uses tools for every number (a measuring tool, a crash-physics simulator, an independent witness recheck), decides the primary cause and writes structured claims.
- **Verification (plain code):**
  - A deterministic checker recomputes every claim against a read-only, hashed evidence store, and **independently recomputes the verdict**. Anything unproven is blocked before it reaches the report.
  - The agent never sees the checker's own answers: `PHYS:*` and `ATTR:*` facts are hidden from it.

**Tech Stack:** Python 3.10+, numpy, scipy, cantools, mcap, the openai SDK (pointed at `https://api.meta.ai/v1`), opencv-python-headless, imageio-ffmpeg, huggingface_hub, pytest. The frontend is a static site (vanilla JS + Plotly from a CDN) hosted on a Hugging Face Static Space.

**Deadline:** submit by **Nov 4, 7:00 PM ET** (2 h buffer before 9 PM). Feature freeze is **Nov 4, 1:00 PM ET**.

## Plan files

| File | Contents | Who / which tool |
|---|---|---|
| `00-overview.md` | Interfaces, Task 0 scaffold, smoke tests, schedule | You + Claude Code, tonight |
| `01-track-a-video.md` | Nexar clips, SAM, lane entry/TTC/danger onset, Spark witness, **real-label video benchmark**, **any-clip mode** | **Muse Code** in worktree `track-a` |
| `02-track-b-vehicle.md` | Profiles, physics, attribution, CAN/MCAP, generator (6 stories), alignment, evidence store, synthetic benchmark | **Claude Code** in worktree `track-b` |
| `03-track-c-trust.md` | **Agent-decides investigator**, checker (claims + verdict), report | **Claude Code** in worktree `track-c` |
| `04-track-d-ui.md` | **Static** replay site: **incident timeline strip**, verdict banner, log toggles, **avoidance map**, claims | **Antigravity** in worktree `track-d` |
| `05-integration.md` | Analyze pipeline, thumbnails, demo cases, **agent benchmark**, README, video, submission | You + Claude Code on `main` |

**Why Muse Code for Track A:** "Use of Meta AI tooling" is a judging criterion, so say in the README that Telltale was partly built with Muse Code. ⚠️ Check whether Muse Code bills to your API credits. If it does, watch the Billing page. The $150 must also cover the product's own SAM, Spark and Wonder calls (about $30–50 expected).

## Data honesty (README + video)
- **Video:** **real** crash clips from the Nexar Collision Prediction Dataset (Nexar Open Data License: attribution required, no resale).
- **Video benchmark:** our automatic danger timestamps compared with **Nexar's own human labels** on 30–50 clips we never hand-tuned.
- **Vehicle logs:** **generated**, with blind randomized faults and clock skew, consistent with the video's lane-entry and impact times. Real ADAS logs are proprietary, which is exactly why an independent tool is needed.
- **Ground truth** lives in `data/ground_truth/` and is never visible to the agent or the checker.
- **Free-credit note:** with free credits, Meta may use the content you send for product improvement. Only send public data (Nexar), never private data.

---

## Shared interfaces (LOCKED in Task 0)

### Evidence IDs: `<SOURCE>:<name>`. All times are **video seconds** after alignment.

| Prefix | Meaning | Visible to agent? |
|---|---|---|
| `VID:` | Video facts: SAM-derived, or the Nexar impact label | ✅ |
| `CAN:` | Vehicle CAN log (decoded, aligned) | ✅ |
| `AV:` | ADAS/MCAP log (decoded, aligned) | ✅ |
| `PROFILE:` | Vehicle thresholds and nominal values | ✅ |
| `DATA:` | Data quality checks | ✅ |
| `WIT:` | Muse Spark witness (full clip) | ✅ |
| `WIT2:` | Independent recheck the agent asked for (appended by tool code) | ✅ |
| `CF:` | Counterfactual runs the agent asked for (appended by tool code) | ✅ |
| `PHYS:` | Checker's own derived latencies and counterfactual | ❌ hidden |
| `ATTR:` | Checker's independent verdict | ❌ hidden |

Main IDs:
- `VID:lane_entry_t`, `VID:impact_t`, `VID:ttc_at_entry_s`, `VID:target_object_id`
- `CAN:clock_offset_s`, `CAN:brake_request_t`, `CAN:pressure_reached_t`, `CAN:speed_at_entry_mps`
- `AV:clock_offset_s`, `AV:first_seen_t`, `AV:brake_request_t`, `AV:handoff_t`, `AV:range_at_first_seen_m`, `AV:rel_speed_mps`
- Thresholds: `PROFILE:perception_threshold_s`, `PROFILE:command_threshold_s`, `PROFILE:actuation_threshold_s`, `PROFILE:human_prt_s`
- Nominal values: `PROFILE:nominal_perception_s`, `PROFILE:nominal_command_s`, `PROFILE:nominal_tau_s`
- Data quality: `DATA:brake_log_complete`, `DATA:max_brake_gap_s`
- Checker-only physics: `PHYS:perception_latency_s`, `PHYS:command_latency_s`, `PHYS:actuation_latency_s`, `PHYS:handoff_margin_s`, `PHYS:brake_tau_est_s`, `PHYS:gap_at_entry_m`, `PHYS:actual_impact_speed_mps`, `PHYS:cf_nominal_contact`, `PHYS:cf_nominal_min_gap_m`, `PHYS:cf_nominal_impact_speed_mps`
- Checker-only verdict: `ATTR:label`, `ATTR:excess_<layer>_s`, `ATTR:noncausal_faults`
- Witness: `WIT:other_vehicle_lane_change_t`, `WIT:other_vehicle_turn_signal`, `WIT:other_vehicle_brake_lights`, `WIT:weather`, `WIT:lighting`, `WIT:road_surface`
- Agent tool outputs: `WIT2:<slug>`, `CF:run<k>_contact`, `CF:run<k>_impact_speed_mps`, `CF:run<k>_min_gap_m`

### Verdict labels and the six generator stories

| Story (hidden) | Expected label | Meaning |
|---|---|---|
| `perception_late` | `PERCEPTION_LATE` | The system noticed the cut-in vehicle late |
| `command_late` | `COMMAND_LATE` | It noticed in time, but the decision to brake came late (planning hesitated) |
| `brake_slow` | `BRAKE_ACTUATION_LATE` | The brake command was on time, but the brakes built pressure too slowly |
| `late_handoff` | `LATE_HANDOFF` | The system gave control back to the human too late to react |
| `unavoidable` | `UNAVOIDABLE` | Everything was on time; physics made contact unavoidable |
| `dropout` | `INCONCLUSIVE` | The brake log has a gap in the decision window |

`NO_FAULT_FOUND` also exists as an output label.

### Files on disk
```
data/clips/<clip_id>.mp4, data/clips/manifest.json, data/clips/NEXAR_LICENSE
data/bench_clips/<nexar_id>.mp4 + bench_manifest.json   real-label video benchmark clips
data/cases/<case_id>/{case.json, vehicle.can.log, adas.mcap}
data/ground_truth/<case_id>.json
cache/sam/<clip_id>.json          cache/sam_bench/<nexar_id>.json
cache/witness/<clip_id>.json      cache/agent/<case_id>.json
cache/thumbs/<case_id>/<name>.jpg cache/bundles/<case_id>.json
cache/agent_bench/<case_id>.json  data/agent_bench/{cases,ground_truth}/
site/   (build output of `telltale export-site`, gitignored; deployed to the HF Static Space by CI)
bench_results.json  video_bench.json  agent_bench.json
```
`ClipEntry`:
```json
{"clip_id": "nx01", "nexar_id": "00822", "file": "nx01.mp4", "fps": 30.0, "width": 1280, "height": 720,
 "time_of_event": 8.0, "time_of_alert": 6.4, "ego_lane_polygon": [[0.40,0.62],[0.60,0.62],[0.85,1.0],[0.15,1.0]]}
```
`time_of_alert` may be `null`. Normalized SAM tracks: `{"fps", "width", "height", "objects": {"<id>": [{"frame": int, "box": [l, t, r, b]}]}}`, with boxes in **pixels**.

---

### Task 0: Scaffold, shared schema, evidence store, CLI (tonight, on `main`, before any worktree)

> ✅ **Done (commit `075a5c8` and follow-ups).** The committed code in the repo is authoritative. It differs slightly from the
> snippets below: `env.example` instead of `.env.example`, no web-server dependencies, `export-site` and a static `serve`
> command, and a `ruff`/`vulture` config. Don't re-run Task 0.

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `env.example`, `telltale/__init__.py`, `telltale/config.py`, `telltale/core/__init__.py`, `telltale/core/schema.py`, `telltale/core/manifest.py`, `telltale/evidence/__init__.py`, `telltale/evidence/store.py`, `telltale/cli.py`
- Create empty `__init__.py` in `telltale/{video,data,physics,logs,bench,verify,agent,report,web,pipeline}`
- Test: `tests/core/test_store.py`

- [ ] **Step 1: Make a real project folder and init git.** Have the session move to e.g. `~/Desktop/telltale`, then run `git init && git checkout -b main`. Free at least **5 GB** of disk.

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "telltale"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "numpy>=1.26", "scipy>=1.11", "cantools>=39", "mcap>=1.1",
  "openai>=1.40", "fastapi>=0.110", "uvicorn>=0.29", "python-dotenv>=1.0",
  "opencv-python-headless>=4.9", "imageio-ffmpeg>=0.5", "huggingface_hub>=0.24",
]

[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]

[project.scripts]
telltale = "telltale.cli:main"

[tool.setuptools.packages.find]
include = ["telltale*"]

[tool.setuptools.package-data]
telltale = ["logs/dbc/*.dbc", "web/static/*"]
```

- [ ] **Step 3: Write `.gitignore` and `env.example`**

`.gitignore`:
```
.env
__pycache__/
*.egg-info/
.pytest_cache/
data/nexar_raw/
vendor/
cache/sam_raw/
```
`env.example`:
```
MODEL_API_KEY=
TELLTALE_AGENT_MODEL=muse-wonder-1.0
TELLTALE_WITNESS_MODEL=muse-spark-1.3
```

- [ ] **Step 4: Write `telltale/config.py`**

```python
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
CLIPS = DATA / "clips"
BENCH_CLIPS = DATA / "bench_clips"
CASES = DATA / "cases"
GROUND_TRUTH = DATA / "ground_truth"
CACHE = ROOT / "cache"
DBC_DIR = Path(__file__).resolve().parent / "logs" / "dbc"

API_BASE = os.environ.get("MODEL_API_BASE", "https://api.meta.ai/v1")
AGENT_MODEL = os.environ.get("TELLTALE_AGENT_MODEL", "muse-wonder-1.0")
WITNESS_MODEL = os.environ.get("TELLTALE_WITNESS_MODEL", "muse-spark-1.3")


def client():
    from openai import OpenAI

    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set. Use replay mode or add it to .env")
    return OpenAI(base_url=API_BASE, api_key=key)
```

- [ ] **Step 5: Write `telltale/core/schema.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["VERIFIED", "UNCORROBORATED", "BLOCKED"]
ClaimType = Literal["timing", "physics", "observation", "attribution", "other"]
LABELS = (
    "PERCEPTION_LATE",
    "COMMAND_LATE",
    "BRAKE_ACTUATION_LATE",
    "LATE_HANDOFF",
    "UNAVOIDABLE",
    "NO_FAULT_FOUND",
    "INCONCLUSIVE",
)
HIDDEN_FROM_AGENT = ("PHYS:", "ATTR:")


@dataclass(frozen=True)
class Fact:
    id: str
    value: float | int | str | bool
    unit: str
    source: str
    derivation: str
    kind: str = "measurement"  # measurement | observation | derived


@dataclass
class Claim:
    text: str
    type: ClaimType
    evidence: list[str]
    assertion: dict | None = None


@dataclass
class CheckResult:
    claim: Claim
    status: Status
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VideoFacts:
    clip_id: str
    fps: float
    lane_entry_t: float
    impact_t: float
    ttc_at_entry: float | None
    target_object_id: str
```

- [ ] **Step 6: Write `telltale/core/manifest.py`**

```python
import json
from pathlib import Path

from telltale.config import BENCH_CLIPS, CLIPS

MANIFEST = CLIPS / "manifest.json"
BENCH_MANIFEST = BENCH_CLIPS / "bench_manifest.json"
DEFAULT_POLYGON = [[0.40, 0.62], [0.60, 0.62], [0.85, 1.0], [0.15, 1.0]]


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"clips": {}}


def save_manifest(m: dict, path: Path = MANIFEST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, indent=2, sort_keys=True))


def get_clip(clip_id: str) -> dict:
    return load_manifest()["clips"][clip_id]
```

- [ ] **Step 7: Write the failing store test `tests/core/test_store.py`**

```python
import pytest

from telltale.core.schema import Fact
from telltale.evidence.store import EvidenceStore


def _facts():
    return [
        Fact("VID:lane_entry_t", 4.0, "s", "VID", "SAM mask entered ego lane"),
        Fact("AV:first_seen_t", 5.35, "s", "AV", "first /adas/tracks message"),
        Fact("ATTR:label", "PERCEPTION_LATE", "", "ATTR", "attribution", "derived"),
    ]


def test_get_has_series():
    s = EvidenceStore(_facts(), {"can.speed_mps": {"t": [0, 1], "v": [20, 19], "unit": "m/s", "source": "CAN"}})
    assert s.has("VID:lane_entry_t") and s.get("AV:first_seen_t").value == 5.35
    assert s.series("can.speed_mps", 0.5, 2)["v"] == [19.0]


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError):
        EvidenceStore(_facts() + [_facts()[0]])


def test_digest_detects_tampering():
    d = EvidenceStore(_facts()).to_json()
    d["facts"][0]["value"] = 9.9
    with pytest.raises(ValueError):
        EvidenceStore.from_json(d)


def test_only_tool_generated_facts_can_be_appended():
    s = EvidenceStore(_facts())
    s2 = s.extended(
        [
            Fact("WIT2:turn_signal", "no", "", "WIT2", "recheck", "observation"),
            Fact("CF:run1_contact", False, "", "CF", "counterfactual", "derived"),
        ]
    )
    assert s2.has("CF:run1_contact") and s2.parent_digest == s.digest
    with pytest.raises(PermissionError):
        s.extended([Fact("PHYS:perception_latency_s", 0.1, "s", "PHYS", "forged")])


def test_agent_view_hides_checker_facts():
    ids = {f.id for f in EvidenceStore(_facts()).agent_facts()}
    assert "ATTR:label" not in ids and "VID:lane_entry_t" in ids
```

- [ ] **Step 8: Run it and confirm it fails.** `pip install -e ".[dev]" && pytest tests/core -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 9: Write `telltale/evidence/store.py`**

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from telltale.core.schema import HIDDEN_FROM_AGENT, Fact

TOOL_PREFIXES = ("WIT2:", "CF:")


class EvidenceStore:
    def __init__(self, facts: list[Fact], series: dict | None = None):
        self._facts: dict[str, Fact] = {}
        for f in facts:
            if f.id in self._facts:
                raise ValueError(f"duplicate fact id {f.id}")
            self._facts[f.id] = f
        self._series = {
            k: {
                "t": [float(x) for x in v["t"]],
                "v": [float(x) for x in v["v"]],
                "unit": v.get("unit", ""),
                "source": v.get("source", ""),
            }
            for k, v in (series or {}).items()
        }
        self.parent_digest: str | None = None
        self.digest = self._compute_digest()

    def _compute_digest(self) -> str:
        payload = {
            "facts": [asdict(self._facts[k]) for k in sorted(self._facts)],
            "series": {k: self._series[k] for k in sorted(self._series)},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def has(self, fid: str) -> bool:
        return fid in self._facts

    def get(self, fid: str) -> Fact:
        return self._facts[fid]

    def facts(self) -> list[Fact]:
        return [self._facts[k] for k in sorted(self._facts)]

    def agent_facts(self) -> list[Fact]:
        return [f for f in self.facts() if not f.id.startswith(HIDDEN_FROM_AGENT)]

    def series_names(self) -> list[str]:
        return sorted(self._series)

    def series(self, name: str, t0: float | None = None, t1: float | None = None) -> dict:
        s = self._series[name]
        idx = [i for i, t in enumerate(s["t"]) if (t0 is None or t >= t0) and (t1 is None or t <= t1)]
        return {"t": [s["t"][i] for i in idx], "v": [s["v"][i] for i in idx], "unit": s["unit"], "source": s["source"]}

    def extended(self, new_facts: list[Fact]) -> "EvidenceStore":
        for f in new_facts:
            if not f.id.startswith(TOOL_PREFIXES):
                raise PermissionError(f"only tool-generated {TOOL_PREFIXES} facts may be appended, got {f.id}")
        child = EvidenceStore(self.facts() + list(new_facts), self._series)
        child.parent_digest = self.digest
        return child

    def verify_integrity(self) -> bool:
        return self._compute_digest() == self.digest

    def to_json(self) -> dict:
        return {
            "digest": self.digest,
            "parent_digest": self.parent_digest,
            "facts": [asdict(f) for f in self.facts()],
            "series": self._series,
        }

    @classmethod
    def from_json(cls, d: dict) -> "EvidenceStore":
        store = cls([Fact(**f) for f in d["facts"]], d["series"])
        if store.digest != d["digest"]:
            raise ValueError("evidence digest mismatch: store was modified")
        store.parent_digest = d.get("parent_digest")
        return store
```

- [ ] **Step 10: Run the tests and confirm they pass.** `pytest tests/core -v` → 5 passed.

- [ ] **Step 11: Write `telltale/cli.py`.** Every command is wired here with lazy imports, so tracks never edit this file.

```python
import argparse
import json


def main(argv=None):
    p = argparse.ArgumentParser(prog="telltale")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch-list")
    s = sub.add_parser("fetch")
    s.add_argument("nexar_id")
    s.add_argument("--clip-id", required=True)
    s = sub.add_parser("add-clip")
    s.add_argument("path")
    s.add_argument("--clip-id", required=True)
    s.add_argument("--event-time", type=float, required=True)
    s = sub.add_parser("lane-preview")
    s.add_argument("clip_id")
    s = sub.add_parser("sam")
    s.add_argument("clip_id")
    s = sub.add_parser("witness")
    s.add_argument("clip_id")
    s = sub.add_parser("video-report")
    s.add_argument("clip_id")
    s = sub.add_parser("video-bench")
    s.add_argument("--n", type=int, default=40)
    s = sub.add_parser("generate")
    s.add_argument("clip_id")
    s.add_argument("--profile", default="car")
    s.add_argument("--story", required=True)
    s.add_argument("--seed", type=int, default=1)
    sub.add_parser("make-demo")
    s = sub.add_parser("analyze")
    s.add_argument("case_id")
    s.add_argument("--live", action="store_true")
    s = sub.add_parser("analyze-all")
    s.add_argument("--live", action="store_true")
    s = sub.add_parser("benchmark")
    s.add_argument("--seeds", type=int, default=4)
    s = sub.add_parser("agent-bench")
    s.add_argument("--n", type=int, default=18)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    if a.cmd == "fetch-list":
        from telltale.data.fetch import print_positive_clips

        print_positive_clips()
    elif a.cmd == "fetch":
        from telltale.data.fetch import fetch_clip

        print(json.dumps(fetch_clip(a.nexar_id, a.clip_id), indent=2))
    elif a.cmd == "add-clip":
        from telltale.data.fetch import add_clip

        print(json.dumps(add_clip(a.path, a.clip_id, a.event_time), indent=2))
    elif a.cmd == "lane-preview":
        from telltale.video.preview import lane_preview

        print(lane_preview(a.clip_id))
    elif a.cmd == "sam":
        from telltale.video.sam import run_sam_for_clip

        print(run_sam_for_clip(a.clip_id))
    elif a.cmd == "witness":
        from telltale.video.witness import run_witness_for_clip

        print(json.dumps(run_witness_for_clip(a.clip_id), indent=2))
    elif a.cmd == "video-report":
        from telltale.video.report import video_report

        print(json.dumps(video_report(a.clip_id), indent=2))
    elif a.cmd == "video-bench":
        from telltale.video.bench import run_video_bench

        print(json.dumps(run_video_bench(a.n)["summary"], indent=2))
    elif a.cmd == "generate":
        from telltale.pipeline.demo import generate_for_clip

        print(generate_for_clip(a.clip_id, a.profile, a.story, a.seed))
    elif a.cmd == "make-demo":
        from telltale.pipeline.demo import make_demo

        print(json.dumps(make_demo(), indent=2))
    elif a.cmd == "analyze":
        from telltale.pipeline.analyze import analyze

        b = analyze(a.case_id, live=a.live)
        print(b["verdict"]["agent_label"], b["verdict"]["status"], b["counts"])
    elif a.cmd == "analyze-all":
        from telltale.pipeline.analyze import analyze_all

        analyze_all(live=a.live)
    elif a.cmd == "benchmark":
        from telltale.bench.run import run_benchmark

        print(json.dumps(run_benchmark(n_seeds=a.seeds)["summary"], indent=2))
    elif a.cmd == "agent-bench":
        from telltale.pipeline.agent_bench import run_agent_bench

        print(json.dumps(run_agent_bench(a.n)["summary"], indent=2))
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("telltale.web.app:app", host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 12: Commit.** `git add -A && git commit -m "chore: scaffold telltale — schema, evidence store, CLI"`

---

### Task S: Smoke tests (tonight; the plan adapts tonight if any fail)

> ✅ Scripts are committed in `scripts/`. Running them needs `MODEL_API_KEY` in `.env` and a payment method on dev.meta.ai.

- [ ] **Step 1: Credits.** ✅ Confirmed: $150 of free credits are active on dev.meta.ai → Billing. Create an API key and put it in `.env` as `MODEL_API_KEY=...`.

- [ ] **Step 2: Write `scripts/smoke_tools.py`**

```python
import json
import sys

from telltale.config import client

model = sys.argv[1] if len(sys.argv) > 1 else "muse-wonder-1.0"
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_fact",
            "description": "Return one evidence fact by id.",
            "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        },
    }
]
r = client().chat.completions.create(
    model=model, tools=tools, messages=[{"role": "user", "content": "Call get_fact with id VID:lane_entry_t."}]
)
m = r.choices[0].message
print(model, "tool_calls:", json.dumps([c.model_dump() for c in (m.tool_calls or [])], indent=2))
```
Run `python scripts/smoke_tools.py muse-wonder-1.0`, then the same with `muse-spark-1.3`. Expected: one `get_fact` call each. **If Wonder fails, set `TELLTALE_AGENT_MODEL=muse-spark-1.3` in `.env`.**

- [ ] **Step 3: Write `scripts/smoke_spark_video.py`**

```python
import sys

from telltale.config import WITNESS_MODEL, client

c = client()
f = c.files.create(file=open(sys.argv[1], "rb"), purpose="user_data")
r = c.responses.create(
    model=WITNESS_MODEL,
    input=[
        {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Does another vehicle change into the camera car's lane? Give the time in seconds.",
                },
                {"type": "input_file", "file_id": f.id},
            ],
        }
    ],
)
print(r.output_text)
```
Run it after Track A's A1 produces a clip: `python scripts/smoke_spark_video.py data/clips/nx01.mp4`.

- [ ] **Step 4: Commit.** `git add scripts && git commit -m "chore: API smoke tests"`

---

## Worktrees and parallel execution (Nov 3)

The tracks don't call each other's code. They build against the **locked formats above** and test with made-up sample data, so A, B and C can run at the same time. D imports B and C, so start D after they merge.

```bash
git worktree add ../telltale-a -b track-a     # Muse Code
git worktree add ../telltale-b -b track-b     # Claude Code (terminal 1)
git worktree add ../telltale-c -b track-c     # Claude Code (terminal 2)
git worktree add ../telltale-d -b track-d     # Antigravity, start after B + C merge
```

Each agent starts with: *"Read docs/plans/00-overview.md and docs/plans/0X-....md. Execute the tasks in order with test-first discipline. Only edit your allowed folders. Commit after each task."*

Folder ownership:
- **A:** `telltale/video/`, `telltale/data/`, `tests/video/`, `data/clips/`, `data/bench_clips/`, `cache/sam*/`, `cache/witness/`
- **B:** `telltale/physics/`, `telltale/logs/`, `telltale/evidence/build.py`, `telltale/evidence/align.py`, `telltale/bench/`, `tests/physics/`, `tests/logs/`, `tests/evidence/`
- **C:** `telltale/verify/`, `telltale/agent/`, `telltale/report/`, `tests/verify/`, `tests/agent/`, `tests/report/`
- **D:** `telltale/web/`, `tests/web/`

**Merge order:** B → A → C → D, then `05-integration.md` on `main`. **You** are the bottleneck: review each agent's work at its commits, and never run more than three agents at once.

## Schedule (ET)

| When | You (main) | A (Muse Code) | B (Claude Code) | C (Claude Code) | D (Antigravity) |
|---|---|---|---|---|---|
| Nov 2 night | Task 0, Task S, message Pavlo | A1 (fetch + curate) | – | – | – |
| Nov 3 8–12 | 10:00 office hours (ask @CV about Nexar + generated logs) | A2–A3 | B1–B5 | C1 | – |
| Nov 3 12–15 | merge B | A4 | B6–B8 | C2 | – |
| Nov 3 15–19 | merge A, C | A5 (video bench, runs in background) | fixes | C3 | D1–D2 |
| Nov 3 19–24 | I1–I3 | A6 | – | fixes | D3 |
| Nov 4 8–13 | I4 (agent bench), I5 (README/deploy) | | | | polish |
| Nov 4 13:00 | **FREEZE**, fresh-clone test | | | | |
| Nov 4 13–17 | I6 video | | | | |
| Nov 4 17–19 | I7 submit + X post | | | | |

**Cut order if behind:** A6 any-clip mode → PDF report → truck in the synthetic benchmark → witness recheck tool → agent benchmark size (n=18 → 6). **Never cut:** the agent-decides + checker-verifies flow, the same-video/different-logs toggle, the counterfactual, the timeline strip, the real-label video benchmark.
