# Telltale — 01 Track A: Video Evidence (suggested tool: Muse Code)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Work only in worktree `../telltale-a` (branch `track-a`). Allowed folders: `telltale/video/`, `telltale/data/`, `tests/video/`, `data/clips/`, `data/bench_clips/`, `cache/sam/`, `cache/sam_bench/`, `cache/witness/`.

**Goal:**
- Real, trimmed Nexar crash clips.
- SAM 3.1 tracks and deterministic video facts: target vehicle, lane entry, TTC, danger onset.
- A Muse Spark witness and recheck.
- A **real-label benchmark** against Nexar's human annotations on 30–50 unseen clips.
- A video-only mode for **any** dashcam clip.

**Interfaces you must honor:** `ClipEntry`, the normalized SAM track format and `VideoFacts`, all in `00-overview.md` / `telltale/core/schema.py`.

**SAM facts already verified from the official cookbook code** (`meta-model-cookbook/07_sam/01_api_basics/python/`):
- The CLI flags are positional `video` (or `--file-id`), `--concept` (required) and `--output` (required directory).
- `summary.json` is a **list** with one object per concept. Each object has keys `concept, media, outcome, records, boxes, masks, tracks, diagnostics`.
- Each box is `{object_id, frame, left, top, right, bottom}`.
- There is no frame-sampling parameter: every frame is processed.
- **Unknown:** whether box coordinates are pixels or 0–1. The code below auto-detects it.

---

### Task A1: Fetch, trim and curate Nexar clips (+ add any clip)

**Files:**
- Create: `telltale/data/fetch.py`, `telltale/video/preview.py`

- [ ] **Step 1: Write `telltale/data/fetch.py`**

```python
import csv
import io
import shutil
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
from huggingface_hub import HfApi, hf_hub_download

from telltale.config import CLIPS, DATA
from telltale.core.manifest import DEFAULT_POLYGON, load_manifest, save_manifest

REPO = "nexar-ai/nexar_collision_prediction"
RAW = DATA / "nexar_raw"
PRE_S, POST_S = 8.0, 1.5


def list_files() -> list[str]:
    return HfApi().list_repo_files(REPO, repo_type="dataset")


def _metadata_csv() -> Path:
    name = next(f for f in list_files() if f.endswith(".csv") and "train" in f.lower())
    return Path(hf_hub_download(REPO, name, repo_type="dataset", local_dir=RAW))


def _id_column(header: list[str]) -> str:
    for c in ("id", "video_id", "clip_id", "file", "filename"):
        if c in header:
            return c
    raise KeyError(f"no id column in {header}")


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def positive_clips() -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(_metadata_csv().read_text())))
    idc = _id_column(list(rows[0].keys()))
    out = []
    for r in rows:
        if str(r.get("label", r.get("target", ""))).strip() in ("1", "1.0") and _f(r.get("time_of_event")) is not None:
            out.append(
                {
                    "nexar_id": r[idc].replace(".mp4", ""),
                    "time_of_event": _f(r["time_of_event"]),
                    "time_of_alert": _f(r.get("time_of_alert")),
                    "scene": r.get("scene", ""),
                    "weather": r.get("weather", ""),
                    "light": r.get("light_conditions", ""),
                }
            )
    return out


def print_positive_clips() -> None:
    for c in positive_clips():
        print(
            f"{c['nexar_id']}\tevent={c['time_of_event']:.2f}s\talert={c['time_of_alert']}\t{c['scene']}\t{c['weather']}\t{c['light']}"
        )


def _video_path(nexar_id: str) -> str:
    return next(f for f in list_files() if f.endswith(f"{nexar_id}.mp4"))


def transcode(src: Path, dst: Path, start: float | None = None, duration: float | None = None) -> None:
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True, capture_output=True)


def _probe(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    d = {
        "fps": float(cap.get(cv2.CAP_PROP_FPS)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    return d


def fetch_trimmed(meta: dict, dest_dir: Path, name: str, delete_raw: bool = False) -> dict:
    """Download one Nexar clip, trim to [event-8s, event+1.5s], return a ClipEntry (no manifest write)."""
    raw = Path(hf_hub_download(REPO, _video_path(meta["nexar_id"]), repo_type="dataset", local_dir=RAW))
    start = max(0.0, meta["time_of_event"] - PRE_S)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / f"{name}.mp4"
    transcode(raw, dst, start, (meta["time_of_event"] - start) + POST_S)
    if delete_raw:
        raw.unlink(missing_ok=True)
    alert = meta.get("time_of_alert")
    return {
        "clip_id": name,
        "nexar_id": meta["nexar_id"],
        "file": dst.name,
        **_probe(dst),
        "time_of_event": round(meta["time_of_event"] - start, 3),
        "time_of_alert": None if alert is None else round(alert - start, 3),
        "ego_lane_polygon": DEFAULT_POLYGON,
    }


def fetch_clip(nexar_id: str, clip_id: str) -> dict:
    meta = next(c for c in positive_clips() if c["nexar_id"] == nexar_id)
    entry = fetch_trimmed(meta, CLIPS, clip_id)
    m = load_manifest()
    m["clips"][clip_id] = entry
    save_manifest(m)
    return entry


def add_clip(path: str, clip_id: str, event_time: float) -> dict:
    """Bring-your-own dashcam clip: re-encode to H.264, register with the impact time you provide."""
    CLIPS.mkdir(parents=True, exist_ok=True)
    dst = CLIPS / f"{clip_id}.mp4"
    transcode(Path(path), dst)
    entry = {
        "clip_id": clip_id,
        "nexar_id": None,
        "file": dst.name,
        **_probe(dst),
        "time_of_event": event_time,
        "time_of_alert": None,
        "ego_lane_polygon": DEFAULT_POLYGON,
    }
    m = load_manifest()
    m["clips"][clip_id] = entry
    save_manifest(m)
    return entry


def copy_license() -> None:
    lic = Path(hf_hub_download(REPO, "LICENSE", repo_type="dataset", local_dir=RAW))
    CLIPS.mkdir(parents=True, exist_ok=True)
    shutil.copy(lic, CLIPS / "NEXAR_LICENSE")
```

- [ ] **Step 2: Check the dataset layout.** Run `python -c "from telltale.data.fetch import list_files; print(list_files()[:40])"`.
  - If the CSV or video paths don't match `_metadata_csv` / `_video_path`, fix only those two functions.
  - Look up the definition of `time_of_alert` in the Nexar paper (arXiv 2503.03848) and **write the exact definition into a comment at the top of `telltale/video/bench.py`** (Task A5).
  - If you get HTTP 401: the user runs `huggingface-cli login` and accepts the dataset terms.

- [ ] **Step 3: Write `telltale/video/preview.py`**

```python
import cv2
import numpy as np

from telltale.config import CACHE, CLIPS
from telltale.core.manifest import get_clip


def lane_preview(clip_id: str) -> str:
    clip = get_clip(clip_id)
    cap = cv2.VideoCapture(str(CLIPS / clip["file"]))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, clip["time_of_event"] - 1.0) * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("could not read frame")
    h, w = frame.shape[:2]
    pts = np.array([[int(x * w), int(y * h)] for x, y in clip["ego_lane_polygon"]], np.int32)
    cv2.polylines(frame, [pts], True, (255, 200, 0), 3)
    out = CACHE / "previews" / f"{clip_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), frame)
    return str(out)
```

- [ ] **Step 4: Curate 4–5 demo clips (manual, about 45 min).**
  1. Run `telltale fetch-list`, then fetch about 12 candidates (`telltale fetch <id> --clip-id nx01`, and so on).
  2. **Keep the clips where a vehicle moves into the camera car's lane ahead and is struck**, in daylight with visible lanes.
  3. For each kept clip, run `telltale lane-preview nxNN` and tune `ego_lane_polygon` in `data/clips/manifest.json`.
  4. Delete the rejects.
  5. Run `python -c "from telltale.data.fetch import copy_license; copy_license()"`.

- [ ] **Step 5: Commit.** `git add telltale/data telltale/video/preview.py data/clips && git commit -m "feat(data): fetch/trim Nexar clips, bring-your-own clip, curation"`

---

### Task A2: SAM 3.1 tracking and normalization

**Files:**
- Create: `telltale/video/sam.py`
- Test: `tests/video/test_sam_normalize.py`

- [ ] **Step 1: Vendor the cookbook and smoke-test it**

```bash
git clone --depth 1 https://github.com/meta-models/meta-model-cookbook vendor/meta-model-cookbook
pip install -r vendor/meta-model-cookbook/07_sam/01_api_basics/requirements.txt
python vendor/meta-model-cookbook/07_sam/01_api_basics/python/02_upload_and_segment_video.py \
  data/clips/nx01.mp4 --concept car --output cache/sam_raw/nx01
python -c "import json; s=json.load(open('cache/sam_raw/nx01/summary.json')); print(type(s), s[0].keys(), s[0]['boxes'][:3])"
```
Expected: a list whose first element has `boxes`. Note whether the coordinates look like pixels (hundreds) or fractions (≤ 1).

- [ ] **Step 2: Write the failing test `tests/video/test_sam_normalize.py`**

```python
from telltale.video.sam import normalize_sam_summary


def test_normalize_groups_by_object_and_sorts_frames():
    summary = [
        {
            "concept": "car",
            "boxes": [
                {"object_id": 3, "frame": 2, "left": 10, "top": 20, "right": 30, "bottom": 40},
                {"object_id": 3, "frame": 1, "left": 11, "top": 21, "right": 31, "bottom": 41},
                {"object_id": 5, "frame": 1, "left": 100, "top": 200, "right": 300, "bottom": 400},
                {"object_id": 9, "frame": None, "left": 0, "top": 0, "right": 1, "bottom": 1},
            ],
        }
    ]
    t = normalize_sam_summary(summary, fps=30.0, width=1000, height=500)
    assert list(t["objects"]) == ["3", "5"]
    assert [d["frame"] for d in t["objects"]["3"]] == [1, 2]
    assert t["objects"]["3"][0]["box"] == [11.0, 21.0, 31.0, 41.0]


def test_fractional_coordinates_are_auto_detected_and_scaled():
    summary = [{"boxes": [{"object_id": 1, "frame": 0, "left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4}]}]
    t = normalize_sam_summary(summary, fps=30.0, width=1000, height=500)
    assert t["objects"]["1"][0]["box"] == [100.0, 100.0, 300.0, 200.0]


def test_accepts_single_object_summary():
    summary = {"boxes": [{"object_id": 1, "frame": 0, "left": 10, "top": 10, "right": 20, "bottom": 20}]}
    assert "1" in normalize_sam_summary(summary, 30.0, 100, 100)["objects"]
```

- [ ] **Step 3: Run it and confirm it fails.** `pytest tests/video/test_sam_normalize.py -v`

- [ ] **Step 4: Write `telltale/video/sam.py`**

```python
import json
import subprocess
import sys
from pathlib import Path

from telltale.config import CACHE, CLIPS, ROOT
from telltale.core.manifest import get_clip

SCRIPT = ROOT / "vendor/meta-model-cookbook/07_sam/01_api_basics/python/02_upload_and_segment_video.py"


def normalize_sam_summary(summary, fps: float, width: int, height: int) -> dict:
    results = summary if isinstance(summary, list) else [summary]
    boxes = [b for b in results[0]["boxes"] if b.get("frame") is not None]
    fractional = bool(boxes) and max(max(b["left"], b["top"], b["right"], b["bottom"]) for b in boxes) <= 1.0
    sx, sy = (width, height) if fractional else (1, 1)
    objects: dict[str, list[dict]] = {}
    for b in boxes:
        box = [float(b["left"]) * sx, float(b["top"]) * sy, float(b["right"]) * sx, float(b["bottom"]) * sy]
        objects.setdefault(str(b["object_id"]), []).append({"frame": int(b["frame"]), "box": box})
    for dets in objects.values():
        dets.sort(key=lambda d: d["frame"])
    return {"fps": fps, "width": width, "height": height, "objects": objects}


def run_sam(video: Path, out_json: Path, fps: float, width: int, height: int, concept: str = "car") -> Path:
    raw_dir = CACHE / "sam_raw" / out_json.stem
    subprocess.run(
        [sys.executable, str(SCRIPT), str(video), "--concept", concept, "--output", str(raw_dir)],
        check=True,
        capture_output=True,
    )
    tracks = normalize_sam_summary(json.loads((raw_dir / "summary.json").read_text()), fps, width, height)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(tracks))
    return out_json


def run_sam_for_clip(clip_id: str, concept: str = "car") -> str:
    c = get_clip(clip_id)
    return str(
        run_sam(CLIPS / c["file"], CACHE / "sam" / f"{clip_id}.json", c["fps"], c["width"], c["height"], concept)
    )
```

- [ ] **Step 5: Run the tests and confirm they pass.** `pytest tests/video/test_sam_normalize.py -v` → 3 passed.

- [ ] **Step 6: Run SAM on every demo clip.** `for c in $(python -c "from telltale.core.manifest import load_manifest; print(' '.join(load_manifest()['clips']))"); do telltale sam $c; done`

- [ ] **Step 7: Commit.** `git add telltale/video/sam.py tests/video cache/sam && git commit -m "feat(video): SAM 3.1 tracking with coordinate auto-detect"`

---

### Task A3: Deterministic video facts (target, lane entry, TTC, danger onset)

**Files:**
- Create: `telltale/video/lane.py`, `telltale/video/ttc.py`, `telltale/video/facts.py`
- Test: `tests/video/test_video_facts.py`

- [ ] **Step 1: Write the failing test `tests/video/test_video_facts.py`**

```python
import math

from telltale.core.manifest import DEFAULT_POLYGON
from telltale.video.facts import compute_video_facts, danger_onset_t
from telltale.video.lane import point_in_polygon
from telltale.video.ttc import ttc_series


def synthetic_tracks():
    target, far = [], []
    for f in range(90):
        cx = 300.0 if f < 30 else min(640.0, 300.0 + (f - 30) * (340.0 / 15.0))
        w = 100.0 + 4.0 * f
        bottom = 500.0 + 2.0 * f
        target.append({"frame": f, "box": [cx - w / 2, bottom - 0.75 * w, cx + w / 2, bottom]})
        far.append({"frame": f, "box": [885.0, 400.0, 915.0, 420.0]})
    return {"fps": 30.0, "width": 1280, "height": 720, "objects": {"1": target, "2": far}}


CLIP = {"clip_id": "syn", "time_of_event": 2.9, "ego_lane_polygon": DEFAULT_POLYGON}


def test_point_in_polygon():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon(5, 5, sq) and not point_in_polygon(15, 5, sq)


def test_target_lane_entry_and_ttc():
    vf = compute_video_facts(synthetic_tracks(), CLIP)
    assert vf.target_object_id == "1"
    assert 32 / 30 <= vf.lane_entry_t <= 37 / 30
    assert vf.impact_t == 2.9
    assert 1.5 < vf.ttc_at_entry < 2.5


def test_danger_onset_is_no_later_than_lane_entry():
    vf = compute_video_facts(synthetic_tracks(), CLIP)
    onset = danger_onset_t(synthetic_tracks(), CLIP)
    assert onset is not None and onset <= vf.lane_entry_t + 1e-9


def test_shrinking_box_has_infinite_ttc():
    dets = [{"frame": f, "box": [0, 0, 200 - f, 100]} for f in range(20)]
    _, ttc = ttc_series(dets, 30.0)
    assert math.isinf(ttc[10])
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/video/lane.py`**

```python
def point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def select_target(objects: dict[str, list[dict]], impact_frame: int, window: int = 5) -> str:
    best = None
    for oid, dets in objects.items():
        near = [d for d in dets if abs(d["frame"] - impact_frame) <= window]
        if not near:
            continue
        l, t, r, b = min(near, key=lambda d: abs(d["frame"] - impact_frame))["box"]
        area = (r - l) * (b - t)
        if best is None or area > best[0]:
            best = (area, oid)
    if best is None:
        raise ValueError("no tracked object visible near the impact frame")
    return best[1]


def lane_entry_frame(dets: list[dict], poly_px, hold: int = 3) -> int | None:
    flags = [point_in_polygon((d["box"][0] + d["box"][2]) / 2, d["box"][3], poly_px) for d in dets]
    for i in range(len(dets) - hold + 1):
        if all(flags[i : i + hold]):
            return dets[i]["frame"]
    return None
```

- [ ] **Step 4: Write `telltale/video/ttc.py`**

```python
import numpy as np


def ttc_series(dets: list[dict], fps: float, smooth: int = 5) -> tuple[np.ndarray, np.ndarray]:
    frames = np.array([d["frame"] for d in dets], dtype=float)
    w = np.array([d["box"][2] - d["box"][0] for d in dets], dtype=float)
    if len(w) < smooth + 2:
        return frames, np.full(len(w), np.inf)
    ws = np.convolve(w, np.ones(smooth) / smooth, mode="same")
    dw = np.gradient(ws, frames / fps)
    with np.errstate(divide="ignore", invalid="ignore"):
        ttc = np.where(dw > 1e-6, ws / dw, np.inf)
    return frames, ttc


def ttc_at(frames: np.ndarray, ttc: np.ndarray, frame: int) -> float | None:
    if len(frames) == 0:
        return None
    v = float(ttc[int(np.argmin(np.abs(frames - frame)))])
    return v if np.isfinite(v) else None


def first_sustained_below(frames: np.ndarray, ttc: np.ndarray, threshold: float, hold: int = 3) -> int | None:
    below = np.isfinite(ttc) & (ttc < threshold)
    for i in range(len(below) - hold + 1):
        if below[i : i + hold].all():
            return int(frames[i])
    return None
```

- [ ] **Step 5: Write `telltale/video/facts.py`**

```python
from telltale.core.schema import VideoFacts
from telltale.video.lane import lane_entry_frame, select_target
from telltale.video.ttc import first_sustained_below, ttc_at, ttc_series

DANGER_TTC_S = 2.0


def _target(tracks: dict, clip: dict):
    fps, W, H = tracks["fps"], tracks["width"], tracks["height"]
    oid = select_target(tracks["objects"], int(round(clip["time_of_event"] * fps)))
    dets = sorted(tracks["objects"][oid], key=lambda d: d["frame"])
    poly = [(x * W, y * H) for x, y in clip["ego_lane_polygon"]]
    return fps, oid, dets, poly


def compute_video_facts(tracks: dict, clip: dict) -> VideoFacts:
    fps, oid, dets, poly = _target(tracks, clip)
    ef = lane_entry_frame(dets, poly)
    if ef is None:
        raise ValueError(f"{clip['clip_id']}: target never enters the ego-lane polygon; adjust the polygon")
    frames, ttc = ttc_series(dets, fps)
    return VideoFacts(
        clip_id=clip["clip_id"],
        fps=fps,
        lane_entry_t=ef / fps,
        impact_t=float(clip["time_of_event"]),
        ttc_at_entry=ttc_at(frames, ttc, ef),
        target_object_id=oid,
    )


def danger_onset_t(tracks: dict, clip: dict) -> float | None:
    """Earliest of: target enters the ego lane, or target TTC stays below 2 s for 3 frames."""
    fps, _, dets, poly = _target(tracks, clip)
    frames, ttc = ttc_series(dets, fps)
    cands = [
        f for f in (lane_entry_frame(dets, poly), first_sustained_below(frames, ttc, DANGER_TTC_S)) if f is not None
    ]
    return min(cands) / fps if cands else None
```

- [ ] **Step 6: Run the tests and confirm they pass.** `pytest tests/video -v`

- [ ] **Step 7: Sanity-check the real clips.** Print `compute_video_facts` for each demo clip. Lane entry should be 0.8–6 s before impact. Adjust a polygon, or drop the clip, if it errors.

- [ ] **Step 8: Commit.** `git add telltale/video tests/video && git commit -m "feat(video): lane entry, target, TTC, danger onset"`

---

### Task A4: Muse Spark witness + independent recheck

**Files:**
- Create: `telltale/video/witness.py`
- Test: `tests/video/test_witness.py`

- [ ] **Step 1: Write the failing test**

```python
from telltale.video.witness import parse_witness_json, witness_facts


def test_parse_strips_code_fences():
    raw = '```json\n{"other_vehicle_turn_signal": "no", "other_vehicle_lane_change_t": 6.1}\n```'
    assert parse_witness_json(raw)["other_vehicle_turn_signal"] == "no"


def test_witness_facts_skip_nulls_and_tag_source():
    facts = witness_facts(
        {"other_vehicle_lane_change_t": None, "other_vehicle_turn_signal": "no", "weather": "clear"},
        model="muse-spark-1.3",
    )
    assert {f.id for f in facts} == {"WIT:other_vehicle_turn_signal", "WIT:weather"}
    assert all(f.source == "WIT" and f.kind == "observation" for f in facts)
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/video/witness.py`**

```python
import json
import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from telltale.config import CACHE, CLIPS, WITNESS_MODEL, client
from telltale.core.manifest import get_clip
from telltale.core.schema import Fact

PROMPT = """You are an impartial traffic-incident witness reviewing a forward dashcam clip.
Report only what is visible. Use "unclear" when you cannot see it. Times are seconds from the clip start.
Return ONLY a JSON object with exactly these keys:
{"other_vehicle_lane_change_t": number or null,
 "other_vehicle_turn_signal": "yes" | "no" | "unclear",
 "other_vehicle_brake_lights": "yes" | "no" | "unclear",
 "weather": short string, "lighting": short string,
 "road_surface": "dry" | "wet" | "snow" | "unclear"}"""
NUMERIC = {"other_vehicle_lane_change_t"}


def parse_witness_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"witness returned no JSON: {text[:200]}")
    return json.loads(m.group(0))


def witness_facts(answers: dict, model: str) -> list[Fact]:
    return [
        Fact(
            f"WIT:{k}",
            float(v) if k in NUMERIC else str(v),
            "s" if k in NUMERIC else "",
            "WIT",
            f"{model} video witness, full clip",
            "observation",
        )
        for k, v in answers.items()
        if v is not None
    ]


def _ask_video(path: Path, prompt: str) -> str:
    c = client()
    with open(path, "rb") as fh:
        f = c.files.create(file=fh, purpose="user_data")
    r = c.responses.create(
        model=WITNESS_MODEL,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}, {"type": "input_file", "file_id": f.id}],
            }
        ],
    )
    return r.output_text


def run_witness_for_clip(clip_id: str) -> dict:
    clip = get_clip(clip_id)
    answers = parse_witness_json(_ask_video(CLIPS / clip["file"], PROMPT))
    out = CACHE / "witness" / f"{clip_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": WITNESS_MODEL, "answers": answers}, indent=2))
    return answers


def recheck(clip_id: str, question: str, t0: float, t1: float, slug: str) -> Fact:
    """Independent second look: trimmed sub-clip, no prior context, one-word answer."""
    clip = get_clip(clip_id)
    with tempfile.TemporaryDirectory() as td:
        sub = Path(td) / "sub.mp4"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-ss",
                f"{t0:.2f}",
                "-i",
                str(CLIPS / clip["file"]),
                "-t",
                f"{max(0.5, t1 - t0):.2f}",
                "-c:v",
                "libx264",
                "-an",
                str(sub),
            ],
            check=True,
            capture_output=True,
        )
        text = _ask_video(sub, f"{question}\nAnswer with ONLY one word: yes, no, or unclear.")
    word = re.search(r"\b(yes|no|unclear)\b", text.lower())
    safe = re.sub(r"[^a-z0-9_]", "_", slug.lower())[:40]
    return Fact(
        f"WIT2:{safe}",
        word.group(1) if word else "unclear",
        "",
        "WIT2",
        f"{WITNESS_MODEL} recheck on sub-clip {t0:.2f}-{t1:.2f}s: {question}",
        "observation",
    )
```

- [ ] **Step 4: Run the tests and confirm they pass.** Then run the witness live on each demo clip with `telltale witness nx01`. Check that `other_vehicle_lane_change_t` is within about 1 s of lane entry.

- [ ] **Step 5: Commit.** `git add telltale/video/witness.py tests/video cache/witness && git commit -m "feat(video): Muse Spark witness + independent recheck"`

---

### Task A5: Real-label video benchmark (answers "you only test on data you made")

**Files:**
- Create: `telltale/video/bench.py`
- Test: `tests/video/test_video_bench.py`

- [ ] **Step 1: Write the failing test (pure summary logic, no network)**

```python
from telltale.video.bench import summarize


def test_summary_metrics():
    rows = [
        {"ok": True, "onset_t": 6.0, "alert_t": 6.2},
        {"ok": True, "onset_t": 5.0, "alert_t": 6.5},
        {"ok": True, "onset_t": None, "alert_t": 6.0},
        {"ok": False, "error": "no target"},
    ]
    s = summarize(rows)
    assert s["n_attempted"] == 4 and s["n_target_found"] == 3 and s["n_onset_found"] == 2
    assert s["median_abs_err_s"] == 0.85
    assert s["within_0_5s"] == 0.5 and s["within_1_0s"] == 0.5
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/video/bench.py`.** Replace the first comment with the `time_of_alert` definition you found in Task A1, Step 2.

```python
# Nexar `time_of_alert` definition (from arXiv 2503.03848): <PASTE EXACT DEFINITION FROM THE PAPER IN TASK A1>
# We compare it with Telltale's automatic danger onset, computed with the DEFAULT lane polygon and no per-clip tuning.
from __future__ import annotations

import json
import random
import statistics
from concurrent.futures import ThreadPoolExecutor

from telltale.config import BENCH_CLIPS, CACHE, ROOT
from telltale.core.manifest import BENCH_MANIFEST, load_manifest, save_manifest
from telltale.video.facts import danger_onset_t
from telltale.video.sam import run_sam


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("ok")]
    found = [r for r in ok if r.get("onset_t") is not None and r.get("alert_t") is not None]
    errs = [abs(r["onset_t"] - r["alert_t"]) for r in found]
    signed = [r["onset_t"] - r["alert_t"] for r in found]
    return {
        "n_attempted": len(rows),
        "n_target_found": len(ok),
        "n_onset_found": len(found),
        "median_abs_err_s": round(statistics.median(errs), 3) if errs else None,
        "mean_signed_err_s": round(statistics.mean(signed), 3) if signed else None,
        "within_0_5s": round(sum(e <= 0.5 for e in errs) / len(errs), 3) if errs else None,
        "within_1_0s": round(sum(e <= 1.0 for e in errs) / len(errs), 3) if errs else None,
    }


def run_video_bench(n: int = 40, seed: int = 7, workers: int = 4) -> dict:
    from telltale.data.fetch import fetch_trimmed, positive_clips

    taken = {c.get("nexar_id") for c in load_manifest()["clips"].values()}
    pool = [c for c in positive_clips() if c["nexar_id"] not in taken and c.get("time_of_alert") is not None]
    random.Random(seed).shuffle(pool)
    bm = load_manifest(BENCH_MANIFEST)
    for meta in pool[:n]:  # sequential downloads (disk-friendly: raw deleted after trimming)
        if meta["nexar_id"] not in bm["clips"]:
            try:
                bm["clips"][meta["nexar_id"]] = fetch_trimmed(meta, BENCH_CLIPS, meta["nexar_id"], delete_raw=True)
            except Exception as e:  # noqa: BLE001 - record and continue
                print("fetch failed", meta["nexar_id"], e)
    save_manifest(bm, BENCH_MANIFEST)

    def one(entry: dict) -> dict:
        out = CACHE / "sam_bench" / f"{entry['clip_id']}.json"
        try:
            if not out.exists():
                run_sam(BENCH_CLIPS / entry["file"], out, entry["fps"], entry["width"], entry["height"])
            onset = danger_onset_t(json.loads(out.read_text()), entry)
            return {
                "nexar_id": entry["clip_id"],
                "ok": True,
                "onset_t": onset,
                "alert_t": entry["time_of_alert"],
                "event_t": entry["time_of_event"],
            }
        except Exception as e:  # noqa: BLE001
            return {"nexar_id": entry["clip_id"], "ok": False, "error": str(e)}

    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, list(bm["clips"].values())[:n]))
    result = {"summary": summarize(rows), "rows": rows}
    (ROOT / "video_bench.json").write_text(json.dumps(result, indent=2))
    return result
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/video/test_video_bench.py -v`

- [ ] **Step 5: Run it live (in the background; about $10 of SAM).** `telltale video-bench --n 40`. Record the summary for the README.
  - **If `median_abs_err_s` is poor, report it honestly** and look at 3–5 failures to understand why (wrong target picked, no lane entry, a crash type that isn't a cut-in).
  - **Never tune on the benchmark clips.** That would invalidate it.

- [ ] **Step 6: Commit.** `git add telltale/video/bench.py tests/video data/bench_clips cache/sam_bench video_bench.json && git commit -m "feat(video): real-label benchmark vs Nexar annotations"`

---

### Task A6: Video-only report for any clip

**Files:**
- Create: `telltale/video/report.py`
- Test: `tests/video/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
import json

import telltale.video.report as rep
from telltale.core.manifest import DEFAULT_POLYGON
from tests.video.test_video_facts import synthetic_tracks


def test_video_only_report_is_honest_about_attribution(tmp_path, monkeypatch):
    clip = {"clip_id": "syn", "time_of_event": 2.9, "ego_lane_polygon": DEFAULT_POLYGON}
    (tmp_path / "sam").mkdir()
    (tmp_path / "sam" / "syn.json").write_text(json.dumps(synthetic_tracks()))
    monkeypatch.setattr(rep, "CACHE", tmp_path)
    monkeypatch.setattr(rep, "get_clip", lambda _c: clip)
    r = rep.video_report("syn")
    assert [e["event"] for e in r["timeline"]][-1] == "impact"
    assert r["attribution"].startswith("INCONCLUSIVE")
```
Also add an empty `tests/__init__.py` and `tests/video/__init__.py` so the import works.

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Write `telltale/video/report.py`**

```python
import json

from telltale.config import CACHE
from telltale.core.manifest import get_clip
from telltale.video.facts import compute_video_facts, danger_onset_t


def video_report(clip_id: str) -> dict:
    clip = get_clip(clip_id)
    tracks = json.loads((CACHE / "sam" / f"{clip_id}.json").read_text())
    vf = compute_video_facts(tracks, clip)
    onset = danger_onset_t(tracks, clip)
    timeline = []
    if onset is not None and onset < vf.lane_entry_t:
        timeline.append({"t": round(onset, 3), "event": "danger onset (time-to-collision under 2 s)"})
    timeline.append({"t": round(vf.lane_entry_t, 3), "event": "vehicle enters ego lane (SAM 3.1)"})
    timeline.append({"t": vf.impact_t, "event": "impact"})
    wpath = CACHE / "witness" / f"{clip_id}.json"
    return {
        "clip_id": clip_id,
        "timeline": timeline,
        "ttc_at_entry_s": vf.ttc_at_entry,
        "witness": json.loads(wpath.read_text())["answers"] if wpath.exists() else None,
        "attribution": "INCONCLUSIVE: attributing cause needs the vehicle's own account (CAN/EDR/ADAS logs). "
        "Add them as a case to run the full investigation.",
    }
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/video -v`

- [ ] **Step 5: Commit.** `git add telltale/video/report.py tests && git commit -m "feat(video): video-only report for any dashcam clip"`
