# Telltale — 04 Track D: Static Replay Site (suggested tool: Antigravity)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Work only in worktree `../telltale-d` (branch `track-d`). Allowed folders: `telltale/web/`, `tests/web/`, plus the one CodeQL line in `.github/workflows/security.yml` (Task D2, Step 4). You import `telltale.physics.*` (Track B) and `telltale.report.render` (Track C). **Start after B and C are merged into `main`**, then `git merge main` into `track-d`.

**Why static:** the demo is hosted on a **free Hugging Face Static Space**, which serves files only (no Python).
- `telltale export-site` turns the cached bundles into a self-contained `site/` folder: HTML, JS, CSS, JSON, clips and thumbnails.
- `telltale serve` serves that same folder locally, so what you test is exactly what judges see.
- The physics stays in Python only. The counterfactual is **pre-computed on a grid** and shown as an **avoidance map**.
- With no server, there's no API surface and no cold start.

**Goal:** one page, no API key needed:
1. **Incident timeline strip**: thumbnail, exact time and gap for each key moment, with the failed link in red.
2. **Verdict banner**: "Concluded by Muse Wonder · independently verified ✓", or "Withheld: checker disagrees".
3. **Vehicle log A/B/C buttons**: same video, different logs, different verdict.
4. **Video with SAM box + ego-lane overlay**, plus an evidence timeline chart.
5. **Avoidance map (but-for test):** impact speed for every combination of detection delay × brake build-up time, with "measured" and "normal" markers.
6. **Machine-checked claims** with BLOCKED and UNCORROBORATED reasons, plus the agent trace and a link to the printable report.

### Bundle format (`cache/bundles/<case_id>.json`, produced in `05-integration.md`). All URLs are **relative**.
```json
{"case_id": "nx01-car-s0101", "clip_id": "nx01", "profile": "car",
 "video_url": "media/nx01.mp4", "fps": 30.0, "width": 1280, "height": 720,
 "lane_polygon": [[0.40,0.62],[0.60,0.62],[0.85,1.0],[0.15,1.0]],
 "target_boxes": [{"frame": 0, "box": [0,0,10,10]}],
 "events": [{"key": "VID:lane_entry_t", "t": 6.0, "label": "Enters our lane", "source": "VID", "thumb": "thumbs/nx01-car-s0101/lane_entry_t.jpg"}],
 "series": {"can.speed_mps": {"t": [], "v": []}, "can.brake_pressure_kpa": {"t": [], "v": []}},
 "facts": [{"id": "...", "value": 1.35, "unit": "s", "source": "AV", "derivation": "...", "kind": "measurement"}],
 "verdict": {"agent_label": "PERCEPTION_LATE", "independent_label": "PERCEPTION_LATE", "status": "VERIFIED",
             "reason": "", "noncausal_faults": [], "excess_s": {"perception": 1.05}},
 "claims": [{"claim": {"text": "...", "type": "timing", "evidence": ["..."], "assertion": {}}, "status": "VERIFIED", "reasons": []}],
 "counts": {"VERIFIED": 6, "UNCORROBORATED": 1, "BLOCKED": 0},
 "digest": "sha256...",
 "agent": {"model": "muse-wonder-1.0", "tool_calls": [{"name": "measure", "args": {"a": "AV:first_seen_t", "b": "VID:lane_entry_t"}}]},
 "counterfactual_inputs": {"v_ego0": 25.0, "v_other": 15.0, "d0": 18.2, "t_end": 4.2,
                           "measured": {"perception_s": 1.35, "command_s": 0.05, "tau_s": 0.15}}}
```

### Site layout (`site/`, a build output that is gitignored)
```
index.html  app.js  style.css   (copied from telltale/web/static/)
cases.json                      [{"case_id", "clip_id", "profile"}]
cases/<case_id>.json            bundle
cf/<case_id>.json               avoidance-map grid
reports/<case_id>.html          printable report (render_html)
media/<clip>.mp4                thumbs/<case_id>/<name>.jpg
README.md                       Hugging Face Space header (sdk: static)
```

---

### Task D1: Site exporter

**Files:**
- Create: `telltale/web/export.py`
- Test: `tests/web/test_export.py`

- [ ] **Step 1: Create a placeholder static folder for the test.** Task D2 replaces these files. Create `telltale/web/static/index.html` containing `<!doctype html><title>Telltale</title>`.

- [ ] **Step 2: Write the failing test `tests/web/test_export.py`**

```python
import json

import pytest

from telltale.web.export import PERCEPTION_GRID, TAU_GRID, export_site

BUNDLE = {
    "case_id": "nx01-car-s0101",
    "clip_id": "nx01",
    "profile": "car",
    "video_url": "media/nx01.mp4",
    "fps": 30.0,
    "width": 1280,
    "height": 720,
    "lane_polygon": [[0.4, 0.62], [0.6, 0.62], [0.85, 1.0], [0.15, 1.0]],
    "target_boxes": [],
    "events": [],
    "series": {},
    "facts": [],
    "verdict": {
        "agent_label": "PERCEPTION_LATE",
        "independent_label": "PERCEPTION_LATE",
        "status": "VERIFIED",
        "reason": "",
        "noncausal_faults": [],
        "excess_s": {},
    },
    "claims": [],
    "counts": {"VERIFIED": 0, "UNCORROBORATED": 0, "BLOCKED": 0},
    "digest": "abc",
    "agent": {"model": "m", "tool_calls": []},
    "counterfactual_inputs": {
        "v_ego0": 25.0,
        "v_other": 15.0,
        "d0": 30.0,
        "t_end": 5.0,
        "measured": {"perception_s": 2.4, "command_s": 0.05, "tau_s": 0.15},
    },
}


@pytest.fixture
def built(tmp_path):
    bundles, clips, thumbs = tmp_path / "bundles", tmp_path / "clips", tmp_path / "thumbs"
    bundles.mkdir()
    clips.mkdir()
    (thumbs / "nx01-car-s0101").mkdir(parents=True)
    (bundles / "nx01-car-s0101.json").write_text(json.dumps(BUNDLE))
    (clips / "nx01.mp4").write_bytes(b"\x00")
    (thumbs / "nx01-car-s0101" / "lane_entry_t.jpg").write_bytes(b"\x00")
    return export_site(bundles, tmp_path / "site", clips_dir=clips, thumbs_dir=thumbs)


def test_site_structure(built):
    assert (built / "index.html").exists()
    assert json.loads((built / "cases.json").read_text()) == [
        {"case_id": "nx01-car-s0101", "clip_id": "nx01", "profile": "car"}
    ]
    assert (built / "cases" / "nx01-car-s0101.json").exists()
    assert (built / "media" / "nx01.mp4").exists()
    assert (built / "thumbs" / "nx01-car-s0101" / "lane_entry_t.jpg").exists()
    assert "does not assign legal fault" in (built / "reports" / "nx01-car-s0101.html").read_text()
    assert "sdk: static" in (built / "README.md").read_text()


def test_avoidance_map_grid(built):
    grid = json.loads((built / "cf" / "nx01-car-s0101.json").read_text())
    assert len(grid["impact_kmh"]) == len(PERCEPTION_GRID)
    assert len(grid["impact_kmh"][0]) == len(TAU_GRID)
    p_late = grid["perception_s"].index(2.4)
    p_nominal = grid["perception_s"].index(0.2)
    tau = grid["tau_s"].index(0.15)
    assert grid["impact_kmh"][p_late][tau] > 0
    assert grid["impact_kmh"][p_nominal][tau] == 0.0


def test_unsafe_case_id_is_rejected(tmp_path):
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / "x.json").write_text(json.dumps({**BUNDLE, "case_id": "../evil"}))
    with pytest.raises(ValueError, match="unsafe case id"):
        export_site(bundles, tmp_path / "site", clips_dir=tmp_path, thumbs_dir=tmp_path)
```

- [ ] **Step 3: Run it and confirm it fails.** `pytest tests/web -v`

- [ ] **Step 4: Write `telltale/web/export.py`**

```python
"""Build the static replay site (Hugging Face Static Space and `telltale serve`) from cached bundles."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np

from telltale.config import CACHE, CLIPS, ROOT
from telltale.physics.counterfactual import counterfactual
from telltale.physics.profiles import PROFILES
from telltale.report.render import render_html

STATIC = Path(__file__).parent / "static"
SITE = ROOT / "site"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
PERCEPTION_GRID = np.round(np.arange(0.0, 2.5001, 0.05), 2)
TAU_GRID = np.round(np.arange(0.05, 2.0001, 0.05), 2)
SPACE_README = """---
title: Telltale
emoji: 🚦
colorFrom: gray
colorTo: red
sdk: static
pinned: false
---

Replay demo of Telltale: Meta AI investigates vehicle crashes; a deterministic checker makes it auditable.
Source: https://github.com/allenvarghese05/telltale
"""


def counterfactual_grid(bundle: dict) -> dict:
    """Impact speed (km/h, 0.0 = avoided) for every detection delay x brake time constant."""
    ci = bundle["counterfactual_inputs"]
    profile = PROFILES[bundle["profile"]]
    command = ci["measured"].get("command_s") or profile.nominal["command_s"]
    impact = []
    for perception in PERCEPTION_GRID:
        row = []
        for tau in TAU_GRID:
            r = counterfactual(
                ci["v_ego0"],
                ci["v_other"],
                ci["d0"],
                profile,
                perception_s=float(perception),
                command_s=command,
                tau=float(tau),
                t_end=ci["t_end"],
            )
            row.append(round(r.impact_rel_speed * 3.6, 1) if r.contact else 0.0)
        impact.append(row)
    return {
        "perception_s": PERCEPTION_GRID.tolist(),
        "tau_s": TAU_GRID.tolist(),
        "impact_kmh": impact,
        "measured": ci["measured"],
        "nominal": {"perception_s": profile.nominal["perception_s"], "tau_s": profile.tau_nominal},
    }


def export_site(
    bundles_dir: Path = CACHE / "bundles",
    out: Path = SITE,
    clips_dir: Path = CLIPS,
    thumbs_dir: Path = CACHE / "thumbs",
) -> Path:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out)
    for sub in ("cases", "cf", "reports", "media", "thumbs"):
        (out / sub).mkdir()
    index = []
    for path in sorted(bundles_dir.glob("*.json")):
        bundle = json.loads(path.read_text())
        case_id = bundle["case_id"]
        if not SAFE_ID.match(case_id):
            raise ValueError(f"unsafe case id {case_id!r} in {path.name}")
        (out / "cases" / f"{case_id}.json").write_text(json.dumps(bundle))
        (out / "cf" / f"{case_id}.json").write_text(json.dumps(counterfactual_grid(bundle)))
        (out / "reports" / f"{case_id}.html").write_text(render_html(bundle))
        clip = Path(bundle["video_url"]).name
        if not (out / "media" / clip).exists():
            shutil.copy(clips_dir / clip, out / "media" / clip)
        if (thumbs_dir / case_id).is_dir():
            shutil.copytree(thumbs_dir / case_id, out / "thumbs" / case_id)
        index.append({"case_id": case_id, "clip_id": bundle["clip_id"], "profile": bundle["profile"]})
    (out / "cases.json").write_text(json.dumps(index))
    (out / "README.md").write_text(SPACE_README)
    return out
```

- [ ] **Step 5: Run the tests and confirm they pass.** `pytest tests/web -v` → 3 passed.

- [ ] **Step 6: Commit.** `git add telltale/web tests/web && git commit -m "feat(web): static site exporter with pre-computed avoidance map"`

---

### Task D2: Frontend

**Files:**
- Replace: `telltale/web/static/index.html`
- Create: `telltale/web/static/app.js`, `telltale/web/static/style.css`

- [ ] **Step 1: Write `index.html`.** Static hosting can't send security headers, so the Content Security Policy lives in a `<meta>` tag.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'self'; script-src 'self' https://cdn.plot.ly; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'">
  <meta name="referrer" content="no-referrer">
  <title>Telltale — Meta AI investigates · the checker verifies</title>
  <link rel="stylesheet" href="style.css">
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
</head>
<body>
<header>
  <div class="brand"><h1>Telltale</h1><span>Meta AI investigates · the checker verifies</span></div>
  <label>Crash clip <select id="clip"></select></label>
  <div id="variants" title="Same video. Different vehicle logs."></div>
</header>
<div id="verdict"></div>
<div id="strip"></div>
<main>
  <section class="col">
    <div id="player"><video id="video" controls muted playsinline></video><canvas id="overlay"></canvas></div>
    <div id="timeline"></div>
    <p class="hint">Real Nexar crash footage · vehicle logs generated with blind fault injection · click any moment to jump.</p>
  </section>
  <section class="col">
    <div class="card">
      <h3>But-for test: would a normal system have avoided it?</h3>
      <div id="cf-out"></div><div id="cf-map"></div>
      <p class="hint">Each cell is a full crash-physics replay. Dark = avoided. ● measured · ◆ normal.</p>
    </div>
    <div class="card"><h3>Investigator claims, each checked <span id="counts"></span></h3><ul id="claim-list"></ul></div>
    <details class="card" id="trace"><summary>Agent trace</summary><ol id="trace-list"></ol></details>
    <a id="report-link" target="_blank" rel="noopener">Open printable report →</a>
  </section>
</main>
<footer id="digest"></footer>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `app.js`**

```javascript
const $ = (id) => document.getElementById(id);
let bundle = null, cases = [];
const LABELS = {
  PERCEPTION_LATE: 'The system detected the hazard late',
  COMMAND_LATE: 'Detected in time — but braking was commanded late',
  BRAKE_ACTUATION_LATE: 'Brakes built pressure too slowly',
  LATE_HANDOFF: 'Control was handed back too late for a human to react',
  UNAVOIDABLE: 'Physically unavoidable — a normal system would still have collided',
  NO_FAULT_FOUND: 'Avoidable, but no layer exceeded tolerance',
  INCONCLUSIVE: 'Inconclusive — evidence is incomplete',
};
const FAILED_LINK = { PERCEPTION_LATE: 'AV:first_seen_t', COMMAND_LATE: 'AV:brake_request_t',
  BRAKE_ACTUATION_LATE: 'CAN:pressure_reached_t', LATE_HANDOFF: 'AV:handoff_t' };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
async function getJSON(u) { const r = await fetch(u); if (!r.ok) throw new Error(`${u}: ${r.status}`); return r.json(); }

async function init() {
  cases = await getJSON('cases.json');
  const clips = [...new Set(cases.map((c) => c.clip_id))];
  $('clip').innerHTML = clips.map((c) => `<option>${esc(c)}</option>`).join('');
  $('clip').onchange = renderVariants;
  renderVariants();
  requestAnimationFrame(loop);
}

function renderVariants() {
  const list = cases.filter((c) => c.clip_id === $('clip').value);
  $('variants').innerHTML = list.map((c, i) =>
    `<button data-id="${esc(c.case_id)}">Vehicle log ${String.fromCharCode(65 + i)} <small>${esc(c.profile)}</small></button>`).join('');
  $('variants').querySelectorAll('button').forEach((b) => (b.onclick = () => load(b.dataset.id)));
  if (list.length) load(list[0].case_id);
}

async function load(id) {
  bundle = await getJSON(`cases/${encodeURIComponent(id)}.json`);
  $('variants').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.id === id));
  const v = $('video');
  if (v.getAttribute('src') !== bundle.video_url) v.src = bundle.video_url;
  renderVerdict(); renderStrip(); drawTimeline(); renderClaims(); renderTrace();
  drawAvoidanceMap(await getJSON(`cf/${encodeURIComponent(id)}.json`));
  $('report-link').href = `reports/${encodeURIComponent(id)}.html`;
  $('digest').textContent = `Evidence digest (SHA-256) ${bundle.digest}`;
}

function renderVerdict() {
  const v = bundle.verdict;
  if (v.status === 'VERIFIED') {
    $('verdict').innerHTML = `<div class="verdict ok"><div class="k">Primary contributing factor</div>
      <div class="v">${esc(LABELS[v.agent_label] || v.agent_label)}</div>
      <div class="badge">Concluded by Muse Wonder · independently verified ✓</div>
      ${v.noncausal_faults.length ? `<div class="note">Faults present but not causal: ${esc(v.noncausal_faults.join(', '))}</div>` : ''}</div>`;
  } else {
    $('verdict').innerHTML = `<div class="verdict rejected"><div class="k">Verdict withheld: checker disagrees</div>
      <div class="v">Investigator said: ${esc(LABELS[v.agent_label] || v.agent_label)}</div>
      <div class="note">${esc(v.reason)}</div></div>`;
  }
}

function renderStrip() {
  const failed = bundle.verdict.status === 'VERIFIED' ? FAILED_LINK[bundle.verdict.agent_label] : null;
  const ev = [...bundle.events].sort((a, b) => a.t - b.t);
  $('strip').innerHTML = ev.map((e, i) => {
    const gap = i ? `<div class="gap ${e.key === failed ? 'bad' : ''}">+${(e.t - ev[i - 1].t).toFixed(2)} s</div>` : '';
    return `${gap}<div class="moment ${e.key === failed ? 'failed' : ''}" data-t="${Number(e.t)}">
      ${e.thumb ? `<img src="${esc(e.thumb)}" alt="">` : '<div class="noimg"></div>'}
      <div class="t">${Number(e.t).toFixed(2)} s</div><div class="l">${esc(e.label)}</div><div class="s">${esc(e.source)}</div></div>`;
  }).join('');
  $('strip').querySelectorAll('.moment').forEach((m) => (m.onclick = () => { $('video').currentTime = +m.dataset.t; }));
}

function loop() { drawOverlay(); requestAnimationFrame(loop); }
function drawOverlay() {
  const v = $('video'), c = $('overlay');
  c.width = v.clientWidth; c.height = v.clientHeight;
  const ctx = c.getContext('2d');
  ctx.clearRect(0, 0, c.width, c.height);
  if (!bundle) return;
  ctx.strokeStyle = 'rgba(80,200,255,.9)'; ctx.lineWidth = 2; ctx.beginPath();
  bundle.lane_polygon.forEach(([x, y], i) => (i ? ctx.lineTo(x * c.width, y * c.height) : ctx.moveTo(x * c.width, y * c.height)));
  ctx.closePath(); ctx.stroke();
  if (!bundle.target_boxes.length) return;
  const f = Math.round(v.currentTime * bundle.fps);
  const d = bundle.target_boxes.reduce((a, b) => (Math.abs(b.frame - f) < Math.abs(a.frame - f) ? b : a));
  if (Math.abs(d.frame - f) > 2) return;
  const sx = c.width / bundle.width, sy = c.height / bundle.height, [l, t, r, b] = d.box;
  ctx.strokeStyle = '#ff4d4f'; ctx.lineWidth = 3; ctx.strokeRect(l * sx, t * sy, (r - l) * sx, (b - t) * sy);
}

function drawTimeline() {
  const s = bundle.series, traces = [];
  if (s['can.speed_mps']) traces.push({ x: s['can.speed_mps'].t, y: s['can.speed_mps'].v.map((x) => x * 3.6), name: 'Speed km/h (CAN)' });
  if (s['can.brake_pressure_kpa']) traces.push({ x: s['can.brake_pressure_kpa'].t, y: s['can.brake_pressure_kpa'].v, name: 'Brake pressure kPa (CAN)', yaxis: 'y2' });
  const shapes = bundle.events.map((e) => ({ type: 'line', x0: e.t, x1: e.t, yref: 'paper', y0: 0, y1: 1, line: { dash: 'dot', width: 1 } }));
  Plotly.newPlot('timeline', traces, {
    height: 240, margin: { t: 10, b: 36, l: 44, r: 50 }, xaxis: { title: 'video time (s)' },
    yaxis: { title: 'km/h' }, yaxis2: { overlaying: 'y', side: 'right', title: 'kPa' }, shapes, legend: { orientation: 'h', y: -0.3 },
  }, { displayModeBar: false, responsive: true });
  $('timeline').on('plotly_click', (ev) => { $('video').currentTime = ev.points[0].x; });
}

function nearest(values, x) { return values.reduce((bi, v, i) => (Math.abs(v - x) < Math.abs(values[bi] - x) ? i : bi), 0); }

function drawAvoidanceMap(g) {
  const m = g.measured, n = g.nominal;
  const mp = nearest(g.perception_s, m.perception_s ?? n.perception_s), mt = nearest(g.tau_s, m.tau_s ?? n.tau_s);
  const np_ = nearest(g.perception_s, n.perception_s), nt = nearest(g.tau_s, n.tau_s);
  const at = (p, t) => g.impact_kmh[p][t];
  $('cf-out').innerHTML = `Measured: ${at(mp, mt) > 0 ? `<b class="bad">collision at ${at(mp, mt).toFixed(1)} km/h</b>` : '<b class="good">avoided</b>'}
    · Normal system: ${at(np_, nt) > 0 ? `<b class="bad">collision at ${at(np_, nt).toFixed(1)} km/h</b>` : '<b class="good">avoided</b>'}`;
  Plotly.newPlot('cf-map', [
    { type: 'heatmap', x: g.tau_s, y: g.perception_s, z: g.impact_kmh, colorscale: 'Reds', zmin: 0, colorbar: { title: 'km/h' },
      hovertemplate: 'detection %{y:.2f} s · brake build-up %{x:.2f} s<br>impact %{z:.1f} km/h<extra></extra>' },
    { type: 'scatter', mode: 'markers', x: [g.tau_s[mt]], y: [g.perception_s[mp]], name: 'measured', marker: { size: 12, symbol: 'circle', color: '#58a6ff', line: { width: 2, color: '#fff' } } },
    { type: 'scatter', mode: 'markers', x: [g.tau_s[nt]], y: [g.perception_s[np_]], name: 'normal', marker: { size: 12, symbol: 'diamond', color: '#3fb950', line: { width: 2, color: '#fff' } } },
  ], { height: 300, margin: { t: 10, b: 40, l: 50, r: 10 }, xaxis: { title: 'brake build-up time constant (s)' },
       yaxis: { title: 'detection delay (s)' }, showlegend: false }, { displayModeBar: false, responsive: true });
}

function renderClaims() {
  $('counts').textContent = `(${bundle.counts.VERIFIED} verified · ${bundle.counts.UNCORROBORATED} single-source · ${bundle.counts.BLOCKED} blocked)`;
  $('claim-list').innerHTML = bundle.claims.map((c) => `<li class="${esc(c.status)}"><span class="chip">${esc(c.status)}</span> ${esc(c.claim.text)}
    <div class="ev">${c.claim.evidence.map(esc).join(' · ')}</div>
    ${c.reasons.length ? `<div class="why">${c.reasons.map(esc).join('<br>')}</div>` : ''}</li>`).join('');
}

function renderTrace() {
  const calls = bundle.agent.tool_calls || [];
  $('trace').querySelector('summary').textContent = `Agent trace — ${bundle.agent.model}, ${calls.length} tool calls`;
  $('trace-list').innerHTML = calls.map((t) => `<li><code>${esc(t.name)}</code> ${esc(JSON.stringify(t.args))}</li>`).join('');
}

init();
```

- [ ] **Step 3: Write `style.css`**

```css
:root { --bg:#0e1116; --card:#161b22; --fg:#e6edf3; --mut:#8b949e; --ok:#3fb950; --warn:#d29922; --bad:#f85149; --acc:#58a6ff; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, sans-serif; }
header { display:flex; gap:16px; align-items:center; padding:12px 20px; border-bottom:1px solid #222; flex-wrap:wrap; }
.brand h1 { margin:0; font-size:20px; } .brand span { color:var(--mut); font-size:12px; }
select, button { background:var(--card); color:var(--fg); border:1px solid #30363d; border-radius:6px; padding:6px 10px; }
#variants button { margin-right:6px; cursor:pointer; } #variants button.active { border-color:var(--acc); box-shadow:0 0 0 1px var(--acc); }
.verdict { margin:14px 20px 0; border-radius:8px; padding:14px; background:#1f2a37; border-left:6px solid var(--acc); }
.verdict.ok { border-color:var(--ok); } .verdict.rejected { border-color:var(--warn); background:#2a2416; }
.verdict .k { color:var(--mut); font-size:12px; text-transform:uppercase; } .verdict .v { font-size:20px; font-weight:600; }
.badge { color:var(--ok); font-size:12px; margin-top:4px; } .note { color:var(--mut); font-size:12px; }
#strip { display:flex; align-items:center; gap:6px; overflow-x:auto; padding:12px 20px; }
.moment { min-width:132px; background:var(--card); border:1px solid #30363d; border-radius:8px; padding:6px; cursor:pointer; text-align:center; }
.moment img, .moment .noimg { width:120px; height:68px; object-fit:cover; border-radius:4px; background:#222; display:block; margin:0 auto; }
.moment .t { font-weight:700; } .moment .l { font-size:12px; } .moment .s { color:var(--mut); font-size:10px; }
.moment.failed { border:2px solid var(--bad); box-shadow:0 0 12px rgba(248,81,73,.35); }
.gap { color:var(--mut); font-size:12px; white-space:nowrap; } .gap.bad { color:var(--bad); font-weight:700; }
main { display:grid; grid-template-columns: 1.25fr 1fr; gap:16px; padding:8px 20px 16px; }
@media (max-width: 1000px) { main { grid-template-columns: 1fr; } }
#player { position:relative; } #player video { width:100%; display:block; border-radius:8px; }
#overlay { position:absolute; inset:0; pointer-events:none; }
.card { background:var(--card); border:1px solid #30363d; border-radius:8px; padding:12px; margin-bottom:12px; }
.card h3 { margin:0 0 8px; font-size:14px; }
#claim-list { list-style:none; padding:0; margin:0; } #claim-list li { padding:8px 0; border-top:1px solid #222; }
.chip { font-size:11px; padding:1px 6px; border-radius:4px; margin-right:6px; }
li.VERIFIED .chip { background:var(--ok); color:#000; } li.UNCORROBORATED .chip { background:var(--warn); color:#000; }
li.BLOCKED .chip { background:var(--bad); color:#fff; }
.ev { color:var(--mut); font-size:11px; } .why { color:var(--bad); font-size:12px; }
.good { color:var(--ok); } .bad { color:var(--bad); } .hint { color:var(--mut); font-size:12px; }
footer { color:var(--mut); font-size:11px; padding:8px 20px 20px; word-break:break-all; } a { color:var(--acc); }
```

- [ ] **Step 4: Enable JavaScript code scanning.** In `.github/workflows/security.yml`, change the CodeQL matrix to `language: [python, javascript-typescript]`.

- [ ] **Step 5: Manual check.** Copy the test's `BUNDLE` into `cache/bundles/` (with any small mp4 at `data/clips/nx01.mp4`), then run `telltale export-site && telltale serve` and open http://127.0.0.1:8000.
  - Check the browser console for **CSP errors**.
  - If Plotly is blocked by the CSP, add `'unsafe-eval'` to `script-src` only, and note it in the commit message.
  - Do the real visual pass after Integration I3.

- [ ] **Step 6: Commit.** `git add telltale/web .github/workflows/security.yml && git commit -m "feat(web): static replay UI — timeline strip, verdict banner, avoidance map"`

---

### Deploy (already wired in CI; nothing to build in this track)
`.github/workflows/deploy.yml` runs after CI passes on `main`: it runs `telltale export-site` and uploads `site/` to the Hugging Face Static Space (`vars.HF_SPACE`, `secrets.HF_TOKEN`) with `huggingface_hub.upload_folder`. It skips itself until `telltale/web/export.py` exists. The Space never receives an API key.
