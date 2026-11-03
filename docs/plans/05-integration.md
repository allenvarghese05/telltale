# Telltale — 05 Integration, Benchmarks, Demo, Submission (main session)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Runs on `main` after the track branches merge. The user drives I6–I7.

**Goal:**
- Wire everything into `analyze`: agent run, verdict check, claim check, timeline thumbnails, bundle.
- Generate the demo cases and cache the live model runs, so replay needs no key.
- Produce **three honest numbers**:
  1. **Video benchmark** vs Nexar human labels (Track A5).
  2. **Synthetic attribution benchmark** (Track B8).
  3. **Agent benchmark**: Muse Wonder alone vs. Wonder + checker.
- Deploy, write the README, record the video, submit by **7 PM ET Nov 4**.

---

### Task I1: Merge tracks

- [ ] **Step 1: Merge in this order.** After each merge, run `pytest -q`.

```bash
git checkout main
git merge --no-ff track-b -m "merge track-b: vehicle logs, physics, evidence"
git merge --no-ff track-a -m "merge track-a: video evidence"
git merge --no-ff track-c -m "merge track-c: agent + checker + report"
git merge --no-ff track-d -m "merge track-d: web app"
```
Expected: all tests pass. Fix integration breaks on `main`, never by weakening tests.

---

### Task I2: Analyze pipeline, demo cases, agent benchmark code

**Files:**
- Create: `telltale/pipeline/analyze.py`, `telltale/pipeline/demo.py`, `telltale/pipeline/agent_bench.py`
- Test: `tests/pipeline/test_analyze.py`, `tests/pipeline/test_agent_bench.py`, `tests/pipeline/__init__.py`

- [ ] **Step 1: Write the failing test `tests/pipeline/test_analyze.py`**

```python
import json

import telltale.pipeline.analyze as an
from telltale.core.manifest import DEFAULT_POLYGON
from telltale.logs.generate import ClipTiming, generate_case
from telltale.physics.profiles import CAR
from telltale.video.facts import compute_video_facts
from tests.video.test_video_facts import synthetic_tracks

CLIP = {
    "clip_id": "syn",
    "file": "syn.mp4",
    "fps": 30.0,
    "width": 1280,
    "height": 720,
    "time_of_event": 2.9,
    "time_of_alert": None,
    "ego_lane_polygon": DEFAULT_POLYGON,
}


def _setup(tmp_path, monkeypatch, agent_verdict):
    cache, cases = tmp_path / "cache", tmp_path / "cases"
    (cache / "sam").mkdir(parents=True)
    (cache / "sam" / "syn.json").write_text(json.dumps(synthetic_tracks()))
    vf = compute_video_facts(synthetic_tracks(), CLIP)
    cid = generate_case(ClipTiming("syn", vf.hazard_onset_t, vf.impact_t), CAR, "brake_slow", 7, cases, tmp_path / "gt")
    (cache / "agent").mkdir()
    (cache / "agent" / f"{cid}.json").write_text(
        json.dumps(
            {
                "model": "fake",
                "digest": "x",
                "verdict": agent_verdict,
                "tool_calls": [],
                "agent_facts": [],
                "claims": [
                    {
                        "text": "The brake request was logged on CAN.",
                        "type": "timing",
                        "evidence": ["CAN:brake_request_t"],
                    },
                    {"text": "The driver was distracted.", "type": "other", "evidence": ["VID:hazard_onset_t"]},
                ],
            }
        )
    )
    for name, val in (("CACHE", cache), ("CASES", cases), ("CLIPS", tmp_path)):
        monkeypatch.setattr(an, name, val)
    monkeypatch.setattr(an, "get_clip", lambda _c: CLIP)
    return cid, cache


def test_analyze_verified(tmp_path, monkeypatch):
    cid, cache = _setup(tmp_path, monkeypatch, "BRAKE_ACTUATION_LATE")
    b = an.analyze(cid)
    assert b["verdict"]["status"] == "VERIFIED" and b["verdict"]["independent_label"] == "BRAKE_ACTUATION_LATE"
    assert b["counts"] == {"VERIFIED": 1, "UNCORROBORATED": 0, "BLOCKED": 1}
    assert b["events"][0]["key"] and "thumb" in b["events"][0]
    assert b["counterfactual_inputs"]["d0"] > 0
    assert (cache / "bundles" / f"{cid}.json").exists()


def test_analyze_rejects_wrong_agent_verdict(tmp_path, monkeypatch):
    cid, _ = _setup(tmp_path, monkeypatch, "PERCEPTION_LATE")
    assert an.analyze(cid)["verdict"]["status"] == "REJECTED"
```

- [ ] **Step 2: Write the failing test `tests/pipeline/test_agent_bench.py` (pure summary)**

```python
from telltale.pipeline.agent_bench import summarize


def test_summary():
    rows = [
        {
            "expected": "PERCEPTION_LATE",
            "agent": "PERCEPTION_LATE",
            "independent": "PERCEPTION_LATE",
            "status": "VERIFIED",
            "counts": {"VERIFIED": 5, "UNCORROBORATED": 1, "BLOCKED": 0},
        },
        {
            "expected": "BRAKE_ACTUATION_LATE",
            "agent": "PERCEPTION_LATE",
            "independent": "BRAKE_ACTUATION_LATE",
            "status": "REJECTED",
            "counts": {"VERIFIED": 3, "UNCORROBORATED": 0, "BLOCKED": 2},
        },
    ]
    s = summarize(rows)
    assert s["n"] == 2 and s["agent_accuracy"] == 0.5 and s["independent_accuracy"] == 1.0
    assert s["agent_wrong"] == 1 and s["agent_wrong_flagged"] == 1 and s["verified_but_wrong"] == 0
    assert s["claims_total"] == 11 and s["claims_blocked"] == 2
```

- [ ] **Step 3: Run them and confirm they fail.** `pytest tests/pipeline -v`

- [ ] **Step 4: Write `telltale/pipeline/analyze.py`**

```python
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import cv2

from telltale.config import AGENT_MODEL, CACHE, CASES, CLIPS, client
from telltale.core.manifest import get_clip
from telltale.core.schema import Claim, Fact
from telltale.evidence.build import build_store
from telltale.physics.counterfactual import counterfactual
from telltale.physics.profiles import PROFILES
from telltale.verify.checker import check_all, check_verdict
from telltale.video.facts import compute_video_facts
from telltale.video.witness import witness_facts

EVENT_LABELS = [
    ("VID:hazard_onset_t", "Becomes a hazard"),
    ("AV:first_seen_t", "System detects it"),
    ("AV:brake_request_t", "System commands braking"),
    ("AV:handoff_t", "Control handed to driver"),
    ("CAN:brake_request_t", "Brake request on CAN"),
    ("CAN:pressure_reached_t", "Brakes engage (60%)"),
    ("VID:impact_t", "Impact"),
]


def build_case_store(case_dir: Path):
    case = json.loads((case_dir / "case.json").read_text())
    clip = get_clip(case["clip_id"])
    profile = PROFILES[case["profile"]]
    tracks = json.loads((CACHE / "sam" / f"{clip['clip_id']}.json").read_text())
    video = compute_video_facts(tracks, clip)
    wpath = CACHE / "witness" / f"{clip['clip_id']}.json"
    extra: list[Fact] = []
    if wpath.exists():
        w = json.loads(wpath.read_text())
        extra = witness_facts(w["answers"], w["model"])
    return clip, profile, tracks, video, build_store(case_dir, video, profile, extra)


def counterfactual_fn(store, profile):
    g = lambda k: float(store.get(k).value)  # noqa: E731
    v0, dv = g("CAN:speed_at_onset_mps"), g("AV:rel_speed_mps")
    d0 = g("AV:range_at_first_seen_m") + dv * (g("AV:first_seen_t") - g("VID:hazard_onset_t"))
    t_end = g("VID:impact_t") - g("VID:hazard_onset_t") + 2.0

    def fn(perception_s: float, command_s: float, tau_s: float) -> dict:
        r = counterfactual(
            v0, v0 - dv, d0, profile, perception_s=perception_s, command_s=command_s, tau=tau_s, t_end=t_end
        )
        return {"contact": r.contact, "impact_speed_mps": r.impact_rel_speed, "min_gap_m": r.min_gap}

    return fn


def agent_run(case_id: str, clip_id: str, store, profile, live: bool, cache_dir: Path | None = None) -> dict:
    path = (cache_dir or CACHE / "agent") / f"{case_id}.json"
    if path.exists() and not live:
        return json.loads(path.read_text())
    from telltale.agent.investigator import investigate
    from telltale.video.witness import recheck

    run = investigate(
        store,
        client(),
        counterfactual_fn=counterfactual_fn(store, profile),
        recheck_fn=lambda q, t0, t1, slug: recheck(clip_id, q, t0, t1, slug),
        model=AGENT_MODEL,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, indent=2))
    return run


def check_run(run: dict, store):
    full = store.extended([Fact(**f) for f in run["agent_facts"]]) if run["agent_facts"] else store
    claims = [
        Claim(
            text=str(c.get("text", "")),
            type=c.get("type", "other"),
            evidence=list(c.get("evidence", [])),
            assertion=c.get("assertion"),
        )
        for c in run["claims"]
    ]
    res = check_all(claims, full)
    rows = [{"claim": asdict(r.claim), "status": r.status, "reasons": r.reasons} for r in res["results"]]
    return full, rows, res["counts"], check_verdict(run["verdict"], full)


def _thumbs(case_id: str, clip: dict, events: list[dict]) -> None:
    cap = cv2.VideoCapture(str(CLIPS / clip["file"]))
    for e in events:
        name = e["key"].split(":")[1]
        out = CACHE / "thumbs" / case_id / f"{name}.jpg"
        e["thumb"] = None
        if not out.exists():
            cap.set(cv2.CAP_PROP_POS_MSEC, e["t"] * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out), cv2.resize(frame, (240, 135)))
        e["thumb"] = f"thumbs/{case_id}/{name}.jpg"
    cap.release()


def analyze(case_id: str, live: bool = False) -> dict:
    clip, profile, tracks, video, store = build_case_store(CASES / case_id)
    run = agent_run(case_id, clip["clip_id"], store, profile, live)
    full, claims, counts, verdict = check_run(run, store)
    f = {x.id: x.value for x in full.facts()}
    events = [{"key": k, "t": f[k], "label": lab, "source": k.split(":")[0]} for k, lab in EVENT_LABELS if k in f]
    _thumbs(case_id, clip, events)
    nc = f.get("ATTR:noncausal_faults", "none")
    verdict.update(
        {
            "noncausal_faults": [] if nc == "none" else nc.split(","),
            "excess_s": {k.split("_", 1)[1][:-2]: v for k, v in f.items() if k.startswith("ATTR:excess_")},
        }
    )
    bundle = {
        "case_id": case_id,
        "clip_id": clip["clip_id"],
        "profile": profile.name,
        "video_url": f"media/{clip['file']}",
        "fps": clip["fps"],
        "width": clip["width"],
        "height": clip["height"],
        "lane_polygon": clip["ego_lane_polygon"],
        "target_boxes": tracks["objects"][video.target_object_id],
        "events": events,
        "series": {k: full.series(k) for k in ("can.speed_mps", "can.brake_pressure_kpa")},
        "facts": [asdict(x) for x in full.facts()],
        "verdict": verdict,
        "claims": claims,
        "counts": counts,
        "digest": full.digest,
        "stale_agent_run": run.get("digest") != store.digest,
        "agent": {"model": run["model"], "tool_calls": run["tool_calls"]},
        "counterfactual_inputs": {
            "v_ego0": f["CAN:speed_at_onset_mps"],
            "v_other": f["CAN:speed_at_onset_mps"] - f["AV:rel_speed_mps"],
            "d0": f["PHYS:gap_at_onset_m"],
            "t_end": round(video.impact_t - video.hazard_onset_t + 2.0, 3),
            "measured": {
                "perception_s": f.get("PHYS:perception_latency_s"),
                "command_s": f.get("PHYS:command_latency_s"),
                "tau_s": f.get("PHYS:brake_tau_est_s"),
            },
        },
    }
    out = CACHE / "bundles" / f"{case_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle))
    return bundle


def analyze_all(live: bool = False) -> list[str]:
    """Analyze every case; returns one summary line per case (the CLI prints them)."""
    lines = []
    for d in sorted(p for p in CASES.iterdir() if (p / "case.json").exists()):
        b = analyze(d.name, live=live)
        lines.append(f"{d.name} {b['verdict']['agent_label']} {b['verdict']['status']} {b['counts']}")
    return lines
```

- [ ] **Step 5: Write `telltale/pipeline/demo.py`**

```python
import json

from telltale.config import CACHE, CASES, GROUND_TRUTH
from telltale.core.manifest import get_clip, load_manifest
from telltale.logs.generate import ClipTiming, GenerationError, generate_case
from telltale.physics.profiles import PROFILES
from telltale.video.facts import compute_video_facts

# One clip, five vehicle logs (UI buttons A..E follow seed order). The truck appears in the benchmarks.
DEMO = [
    ("car", "perception_late", 101),
    ("car", "command_late", 102),
    ("car", "brake_slow", 103),
    ("car", "late_handoff", 104),
    ("car", "unavoidable", 105),
]


def clip_timing(clip_id: str) -> ClipTiming:
    vf = compute_video_facts(json.loads((CACHE / "sam" / f"{clip_id}.json").read_text()), get_clip(clip_id))
    return ClipTiming(clip_id, vf.hazard_onset_t, vf.impact_t)


def generate_for_clip(clip_id: str, profile: str, story: str, seed: int) -> str:
    return generate_case(clip_timing(clip_id), PROFILES[profile], story, seed, CASES, GROUND_TRUTH)


def make_demo() -> dict:
    made, skipped = [], []
    for clip_id in load_manifest()["clips"]:
        for profile, story, seed in DEMO:
            try:
                made.append(generate_for_clip(clip_id, profile, story, seed))
            except GenerationError as e:
                skipped.append(f"{clip_id}/{story}: {e}")
    return {"cases": made, "skipped": skipped}
```

- [ ] **Step 6: Write `telltale/pipeline/agent_bench.py`**

```python
from __future__ import annotations

import json
import random

from telltale.config import CACHE, DATA, ROOT
from telltale.core.manifest import load_manifest
from telltale.logs.generate import EXPECTED, STORIES, GenerationError, generate_case
from telltale.physics.profiles import CAR
from telltale.pipeline.analyze import agent_run, build_case_store, check_run
from telltale.pipeline.demo import clip_timing

ROOT_DIR = DATA / "agent_bench"


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    wrong = [r for r in rows if r["agent"] != r["expected"]]
    return {
        "n": n,
        "agent_accuracy": round(sum(r["agent"] == r["expected"] for r in rows) / max(n, 1), 3),
        "independent_accuracy": round(sum(r["independent"] == r["expected"] for r in rows) / max(n, 1), 3),
        "agent_wrong": len(wrong),
        "agent_wrong_flagged": sum(r["status"] == "REJECTED" for r in wrong),
        "verified_but_wrong": sum(r["status"] == "VERIFIED" and r["agent"] != r["expected"] for r in rows),
        "claims_total": sum(sum(r["counts"].values()) for r in rows),
        "claims_blocked": sum(r["counts"]["BLOCKED"] for r in rows),
        "claims_uncorroborated": sum(r["counts"]["UNCORROBORATED"] for r in rows),
    }


def run_agent_bench(n: int = 18, seed: int = 3) -> dict:
    combos = [(c, s) for c in load_manifest()["clips"] for s in STORIES]
    random.Random(seed).shuffle(combos)
    rows = []
    for i, (clip_id, story) in enumerate(combos[:n]):
        case_id = f"{clip_id}-car-s{5000 + i:04d}"
        case_dir = ROOT_DIR / "cases" / case_id
        if not case_dir.exists():
            try:
                generate_case(clip_timing(clip_id), CAR, story, 5000 + i, ROOT_DIR / "cases", ROOT_DIR / "ground_truth")
            except GenerationError:
                continue
        _, profile, _, _, store = build_case_store(case_dir)
        run = agent_run(case_id, clip_id, store, profile, live=False, cache_dir=CACHE / "agent_bench")
        _, _, counts, verdict = check_run(run, store)
        rows.append(
            {
                "case": case_id,
                "expected": EXPECTED[story],
                "agent": run["verdict"],
                "independent": verdict["independent_label"],
                "status": verdict["status"],
                "counts": counts,
            }
        )
        print(case_id, story, run["verdict"], verdict["status"], counts)
    result = {"summary": summarize(rows), "rows": rows}
    (ROOT / "agent_bench.json").write_text(json.dumps(result, indent=2))
    return result
```
`agent_run(..., live=False)` still calls the live API when there's no cached run, then caches it. Re-running is free.

- [ ] **Step 7: Run the tests and confirm they pass.** `pytest -q` → all pass.

- [ ] **Step 8: Commit.** `git add telltale/pipeline tests/pipeline && git commit -m "feat(pipeline): analyze with verdict check + thumbnails, demo cases, agent benchmark"`

---

### Task I3: Demo data + live agent runs (Nov 3 evening)

- [ ] **Step 1: Generate the demo cases.** `telltale make-demo`. Expect about 5 cases per clip, and report any skips.
- [ ] **Step 2: Run the agent live once per case (cached afterwards).** `telltale analyze-all --live`. Watch the Billing page.
  - Expect mostly **VERIFIED** verdicts and claims.
  - If many claims get BLOCKED for formatting (rounding, units), improve the example in `SYSTEM` (Track C2). **Never loosen the checker.**
- [ ] **Step 3: Visual check.** `telltale serve`. Walk through every case and pick the **hero clip** for the video: the best footage, with all five log variants verified.
- [ ] **Step 4: Note every natural catch** (a REJECTED verdict, or BLOCKED/UNCORROBORATED claims). These are the authentic "checker caught it" moments for the video. **Never hand-edit cached runs.**
- [ ] **Step 5: Commit the replay data.** `git add data/clips data/cases data/ground_truth cache/sam cache/witness cache/agent cache/thumbs cache/bundles && git commit -m "data: demo cases and cached runs"`

---

### Task I4: The three benchmarks (Nov 4 morning; runs in the background)

- [ ] **Step 1: Synthetic attribution.** `telltale benchmark --seeds 4` → `bench_results.json`
- [ ] **Step 2: Agent vs. agent + checker.** `telltale agent-bench --n 18` → `agent_bench.json` (about $10–15)
- [ ] **Step 3: Video vs. Nexar human labels.** Already run in Track A5 → `video_bench.json`
- [ ] **Step 4: Copy the headline numbers into the README** (Task I5). Commit: `git add bench_results.json agent_bench.json video_bench.json data/agent_bench cache/agent_bench && git commit -m "bench: results"`

---

### Task I5: README, fresh-clone test, hosted demo (before the 1 PM freeze)

- [ ] **Step 1: Write `README.md`.** Use these sections; fill the numbers from Task I4.

````markdown
# Telltale: Meta AI investigates crashes. A checker makes it auditable.

When a car with driver-assist crashes, everyone asks: was it the other driver, the software, the brakes,
or physics? Today a reconstruction expert takes weeks and tens of thousands of dollars to answer, and the
vehicle vendor is a conflicted party.

**How Telltale works**
1. **Meta AI sees:** SAM 3.1 tracks the vehicles in real dashcam footage and timestamps lane entry.
   Muse Spark 1.3 watches as a witness (signals, brake lights, weather).
2. **Meta AI investigates:** a Muse Wonder agent reads the vehicle's CAN and ADAS logs. It measures every
   interval with tools, runs but-for crash simulations, asks for independent rechecks of what the witness saw,
   decides the primary cause, and writes structured findings.
3. **Code verifies:** a deterministic checker recomputes every claim and independently recomputes the verdict
   from the same evidence. Unproven, legal-conclusion and driver-state claims are blocked. A disagreeing verdict
   is withheld for human review.

## Results (honest numbers)
| Benchmark | Result |
|---|---|
| Video timeline vs **Nexar human labels** on N unseen real crashes (no per-clip tuning) | median error X s; Y% within 1 s |
| Muse Wonder verdict accuracy (alone) | A% |
| Wrong agent verdicts caught by the checker | B of C |
| Claims reaching the report unverified | 0 (D blocked, E single-source labelled) |
| Synthetic blind attribution (6 failure types, car + Class 8 truck profiles) | F%, abstains on corrupted logs G% |

## Run it in 2 minutes (no API key)
```bash
pip install -e . && telltale export-site && telltale serve    # http://127.0.0.1:8000
```

## Run it on your own clip / with your own key
```bash
cp env.example .env                    # MODEL_API_KEY
telltale add-clip my_dashcam.mp4 --clip-id mine --event-time 7.4
telltale sam mine && telltale witness mine && telltale video-report mine
```
Without the vehicle's logs, Telltale reports the video timeline and says **INCONCLUSIVE** for cause. That's by design.

## Data honesty
- Video: real crash clips from the Nexar Collision Prediction Dataset, under the Nexar Open Data License (`data/clips/NEXAR_LICENSE`). Attribution: Moura & Zvitia, "Nexar Collision Dataset", Hugging Face, 2025.
- Vehicle logs are generated (`telltale/logs/generate.py`): consistent with each video's lane-entry and impact times, with hidden randomized faults and clock skew, because real ADAS logs are proprietary. Ground truth is never visible to the agent or the checker.
- Built during the hackathon (Oct 26 – Nov 4, 2026), partly with Muse Code.

## Limits
Telltale reconstructs evidence; it does not assign legal fault. Monocular video gives timing and TTC, not absolute distance. The physics is 1-D longitudinal.
````

- [ ] **Step 2: Fresh-clone test (what a judge does).**

```bash
cd /tmp && rm -rf tt && git clone <public-repo-url> tt && cd tt
python3.12 -m venv .venv && . .venv/bin/activate && pip install -e . && telltale export-site && telltale serve
```
Expected: everything works with **no API key**.

- [ ] **Step 3: Hosted demo (automatic).**
  1. The Static Space `Allen05254/telltale` is already wired: CI's `Deploy demo` workflow exports and uploads `site/` after every green push to `main`.
  2. Push, wait for **Deploy demo** to go green, open https://huggingface.co/spaces/Allen05254/telltale, and put that URL at the top of the README.
  3. **Never add `MODEL_API_KEY` to the Space.**

- [ ] **Step 4: 1:00 PM ET FEATURE FREEZE.** Push. From here on, only bug fixes.

---

### Task I6: Demo video (1–5 PM ET; you record)

Keep it to **3:00 or less**, in English, at 1080p. The framing throughout: **Meta AI does the work; the checker makes it auditable.**

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:10 | Real Nexar crash clip, full screen | "A car cuts in. Impact. Who caused it: the other driver, the software, or the brakes?" |
| 0:10–0:25 | Three stat cards | "A 2025 jury split a fatal driver-assist crash 67/33 between driver and carmaker: $243 million. Reconstructions take weeks. And video alone can't answer it." |
| 0:25–0:55 | Telltale: timeline strip with thumbnails, SAM box on video | "SAM 3.1 tracks the vehicle and timestamps the exact frame it enters our lane. Here's every key moment: detection, brake command, brakes engaging, impact. The late link is in red." |
| 0:55–1:20 | Verdict banner + agent trace scrolling | "Muse Wonder investigates. It measures every interval with tools, runs crash simulations, and asks Muse Spark for an independent second look. Then it concludes: detection was 1.35 seconds late." |
| 1:20–1:45 | Click Vehicle log A → B → C → E | "Same video. Different vehicle logs. Detection late. Braking decision late. Brakes slow. Physically unavoidable. The footage never changes. That's why you need both, checked against each other." |
| 1:45–2:00 | Drag the slider to normal | "The but-for test: with normal detection, this crash doesn't happen." |
| 2:00–2:25 | Claims panel: a real BLOCKED / UNCORROBORATED / REJECTED example from Task I3 Step 4 | "Every claim it makes is recomputed by a deterministic checker before anyone sees it. Here it cited a signal observation from one source only, so it's labelled unconfirmed. We made Muse auditable." |
| 2:25–2:45 | Results table | "On N real crashes it never saw, our video timeline matched Nexar's human labels within X seconds. And across Y investigations, no unverified claim reached a report." |
| 2:45–3:00 | Architecture slide → logo | "SAM 3.1, Muse Spark, Muse Wonder, built partly with Muse Code. Telltale: Meta AI investigates. The checker makes it auditable." |

- [ ] **Step 1:** Record with QuickTime → Screen Recording; voice-over can be recorded separately. Add a 10-second real-person quote (Pavlo or another driver/adjuster) if you got one.
- [ ] **Step 2:** Edit to 3:00 or less, upload to YouTube (unlisted) or Vimeo, and check the link in a private window.

---

### Task I7: Submit (5–7 PM ET)

- [ ] **Step 1: Checklist.**
  - Repo is public; the README has the data honesty section; the Nexar license file is present.
  - No keys anywhere: `git log -p | grep -i "MODEL_API_KEY="` should show only the empty example.
  - Video is 3:00 or less and the link works; the hosted URL works.
  - Track: **Indie**. Theme: **Push the Frontier**.
- [ ] **Step 2:** Submit at https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit **by 7 PM ET**. Screenshot the confirmation.
- [ ] **Step 3 (Most Viral):** post the 1:20–1:45 "same video, different logs" segment on X with the repo link, then submit the post link on the platform.
