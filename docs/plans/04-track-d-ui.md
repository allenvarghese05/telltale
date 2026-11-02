# Telltale — 04 Track D: Web App, Replay Mode, Deploy (suggested tool: Antigravity)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Work only in worktree `../telltale-d` (branch `track-d`). Allowed folders: `telltale/web/`, `tests/web/`, `Dockerfile`, `.dockerignore`. You import `telltale.physics.*` (Track B) and `telltale.report.render` (Track C). **Start after B and C are merged into `main`**, then `git merge main` into `track-d`.

**Goal:** a single page that replays cached cases with no API key:
1. **Incident timeline strip**: a thumbnail, exact time and gap for each key moment, with the failed link in red.
2. **Verdict banner**: "Concluded by Muse Wonder · independently verified ✓", or "Withheld: checker disagrees".
3. **Vehicle log A/B/C buttons**: same video, different logs, different verdict.
4. **Video with SAM box + ego-lane overlay**, and an evidence timeline chart.
5. **Counterfactual slider** (but-for test).
6. **Machine-checked claims** with BLOCKED and UNCORROBORATED reasons, plus the agent trace.

### Bundle format (`cache/bundles/<case_id>.json`, produced in `05-integration.md`)
```json
{"case_id": "nx01-car-s0101", "clip_id": "nx01", "profile": "car",
 "video_url": "/media/nx01.mp4", "fps": 30.0, "width": 1280, "height": 720,
 "lane_polygon": [[0.40,0.62],[0.60,0.62],[0.85,1.0],[0.15,1.0]],
 "target_boxes": [{"frame": 0, "box": [0,0,10,10]}],
 "events": [{"key": "VID:lane_entry_t", "t": 6.0, "label": "Enters our lane", "source": "VID", "thumb": "/thumbs/nx01-car-s0101/lane_entry_t.jpg"}],
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

---

### Task D1: API

**Files:**
- Create: `telltale/web/app.py`
- Test: `tests/web/test_app.py`

- [ ] **Step 1: Write the failing test `tests/web/test_app.py`**

```python
import json

import pytest
from fastapi.testclient import TestClient

import telltale.web.app as webapp

BUNDLE = {
    "case_id": "nx01-car-s0101",
    "clip_id": "nx01",
    "profile": "car",
    "video_url": "/media/nx01.mp4",
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
        "measured": {"perception_s": 2.9, "command_s": 0.05, "tau_s": 0.15},
    },
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "nx01-car-s0101.json").write_text(json.dumps(BUNDLE))
    monkeypatch.setattr(webapp, "BUNDLES", tmp_path)
    return TestClient(webapp.app)


def test_cases_list(client):
    assert client.get("/api/cases").json() == [{"case_id": "nx01-car-s0101", "clip_id": "nx01", "profile": "car"}]


def test_case_bundle_and_404(client):
    assert client.get("/api/case/nx01-car-s0101").json()["verdict"]["status"] == "VERIFIED"
    assert client.get("/api/case/nope").status_code == 404


def test_counterfactual_slider_flips_outcome(client):
    late = client.get("/api/counterfactual/nx01-car-s0101", params={"perception": 2.9, "tau": 0.15}).json()
    nominal = client.get("/api/counterfactual/nx01-car-s0101", params={"perception": 0.2, "tau": 0.15}).json()
    assert late["contact"] and not nominal["contact"]
    assert len(nominal["t"]) <= 400 and len(nominal["t"]) == len(nominal["gap"])


def test_report_and_index(client):
    assert "does not assign legal fault" in client.get("/report/nx01-car-s0101").text
    assert "Telltale" in client.get("/").text
```

- [ ] **Step 2: Run it and confirm it fails.** `pytest tests/web -v`

- [ ] **Step 3: Write `telltale/web/app.py`**

```python
import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from telltale.config import CACHE, CLIPS
from telltale.physics.counterfactual import counterfactual
from telltale.physics.profiles import PROFILES
from telltale.report.render import render_html

STATIC = Path(__file__).parent / "static"
BUNDLES = CACHE / "bundles"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

app = FastAPI(title="Telltale")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/media", StaticFiles(directory=CLIPS, check_dir=False), name="media")
app.mount("/thumbs", StaticFiles(directory=CACHE / "thumbs", check_dir=False), name="thumbs")


def _bundle(case_id: str) -> dict:
    p = BUNDLES / f"{case_id}.json"
    if not SAFE_ID.match(case_id) or not p.exists():
        raise HTTPException(404, "unknown case")
    return json.loads(p.read_text())


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/cases")
def cases():
    out = []
    for p in sorted(BUNDLES.glob("*.json")):
        b = json.loads(p.read_text())
        out.append({"case_id": b["case_id"], "clip_id": b["clip_id"], "profile": b["profile"]})
    return out


@app.get("/api/case/{case_id}")
def case(case_id: str):
    return _bundle(case_id)


@app.get("/api/counterfactual/{case_id}")
def cf(case_id: str, perception: float, tau: float, command: float | None = None):
    b = _bundle(case_id)
    ci, prof = b["counterfactual_inputs"], PROFILES[b["profile"]]
    cmd = command if command is not None else (ci["measured"].get("command_s") or prof.nominal["command_s"])
    r = counterfactual(
        ci["v_ego0"], ci["v_other"], ci["d0"], prof, perception_s=perception, command_s=cmd, tau=tau, t_end=ci["t_end"]
    )
    step = max(1, len(r.t) // 300)
    return {
        "contact": bool(r.contact),
        "impact_speed_kmh": r.impact_rel_speed * 3.6,
        "min_gap_m": r.min_gap,
        "t": r.t[::step].round(3).tolist(),
        "gap": r.gap[::step].round(3).tolist(),
    }


@app.get("/report/{case_id}", response_class=HTMLResponse)
def report(case_id: str):
    return render_html(_bundle(case_id))
```

- [ ] **Step 4: Commit** (the tests pass once Task D2 adds `index.html`). `git add telltale/web tests/web && git commit -m "feat(web): replay API, counterfactual, report, thumbnails"`

---

### Task D2: Frontend

**Files:**
- Create: `telltale/web/static/index.html`, `telltale/web/static/app.js`, `telltale/web/static/style.css`

- [ ] **Step 1: Write `index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Telltale — independent, verifiable crash causation</title>
  <link rel="stylesheet" href="/static/style.css">
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
      <h3>But-for test: what if this had been normal?</h3>
      <label>Detection delay <input id="cf-p" type="range" min="0" max="2.5" step="0.05"> <b id="cf-p-v"></b> s</label>
      <label>Brake build-up time <input id="cf-tau" type="range" min="0.05" max="2" step="0.05"> <b id="cf-tau-v"></b> s</label>
      <div id="cf-out"></div><div id="cf-plot"></div>
    </div>
    <div class="card"><h3>Investigator claims, each checked <span id="counts"></span></h3><ul id="claim-list"></ul></div>
    <details class="card" id="trace"><summary>Agent trace</summary><ol id="trace-list"></ol></details>
    <a id="report-link" target="_blank" rel="noopener">Open printable report →</a>
  </section>
</main>
<footer id="digest"></footer>
<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `app.js`**

```javascript
const $ = (id) => document.getElementById(id);
let bundle = null, cases = [], cfTimer = null;
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
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
async function getJSON(u) { const r = await fetch(u); if (!r.ok) throw new Error(`${u}: ${r.status}`); return r.json(); }

async function init() {
  cases = await getJSON('/api/cases');
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
  bundle = await getJSON(`/api/case/${id}`);
  $('variants').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.id === id));
  const v = $('video');
  if (!v.src.endsWith(bundle.video_url)) v.src = bundle.video_url;
  renderVerdict(); renderStrip(); drawTimeline(); renderClaims(); renderTrace(); initCF();
  $('report-link').href = `/report/${id}`;
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
    return `${gap}<div class="moment ${e.key === failed ? 'failed' : ''}" data-t="${e.t}">
      ${e.thumb ? `<img src="${esc(e.thumb)}" alt="">` : '<div class="noimg"></div>'}
      <div class="t">${e.t.toFixed(2)} s</div><div class="l">${esc(e.label)}</div><div class="s">${esc(e.source)}</div></div>`;
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

function renderClaims() {
  $('counts').textContent = `(${bundle.counts.VERIFIED} verified · ${bundle.counts.UNCORROBORATED} single-source · ${bundle.counts.BLOCKED} blocked)`;
  $('claim-list').innerHTML = bundle.claims.map((c) => `<li class="${c.status}"><span class="chip">${c.status}</span> ${esc(c.claim.text)}
    <div class="ev">${c.claim.evidence.map(esc).join(' · ')}</div>
    ${c.reasons.length ? `<div class="why">${c.reasons.map(esc).join('<br>')}</div>` : ''}</li>`).join('');
}

function renderTrace() {
  const calls = bundle.agent.tool_calls || [];
  $('trace').querySelector('summary').textContent = `Agent trace — ${bundle.agent.model}, ${calls.length} tool calls`;
  $('trace-list').innerHTML = calls.map((t) => `<li><code>${esc(t.name)}</code> ${esc(JSON.stringify(t.args))}</li>`).join('');
}

function initCF() {
  const m = bundle.counterfactual_inputs.measured;
  $('cf-p').value = m.perception_s ?? 0.2;
  $('cf-tau').value = m.tau_s ?? 0.15;
  $('cf-p').oninput = $('cf-tau').oninput = runCF;
  runCF();
}

function runCF() {
  $('cf-p-v').textContent = (+$('cf-p').value).toFixed(2);
  $('cf-tau-v').textContent = (+$('cf-tau').value).toFixed(2);
  clearTimeout(cfTimer);
  cfTimer = setTimeout(async () => {
    const r = await getJSON(`/api/counterfactual/${bundle.case_id}?perception=${$('cf-p').value}&tau=${$('cf-tau').value}`);
    $('cf-out').innerHTML = r.contact ? `<b class="bad">Collision</b> at ${r.impact_speed_kmh.toFixed(1)} km/h closing speed`
      : `<b class="good">Avoided</b> — closest gap ${r.min_gap_m.toFixed(2)} m`;
    Plotly.newPlot('cf-plot', [{ x: r.t, y: r.gap, name: 'gap (m)' }], {
      height: 160, margin: { t: 6, b: 32, l: 40, r: 10 }, xaxis: { title: 's after lane entry' }, yaxis: { title: 'gap m' },
      shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: '#ff4d4f' } }],
    }, { displayModeBar: false, responsive: true });
  }, 120);
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
.card h3 { margin:0 0 8px; font-size:14px; } .card label { display:block; margin:4px 0; color:var(--mut); }
#claim-list { list-style:none; padding:0; margin:0; } #claim-list li { padding:8px 0; border-top:1px solid #222; }
.chip { font-size:11px; padding:1px 6px; border-radius:4px; margin-right:6px; }
li.VERIFIED .chip { background:var(--ok); color:#000; } li.UNCORROBORATED .chip { background:var(--warn); color:#000; }
li.BLOCKED .chip { background:var(--bad); color:#fff; }
.ev { color:var(--mut); font-size:11px; } .why { color:var(--bad); font-size:12px; }
.good { color:var(--ok); } .bad { color:var(--bad); } .hint { color:var(--mut); font-size:12px; }
footer { color:var(--mut); font-size:11px; padding:8px 20px 20px; word-break:break-all; } a { color:var(--acc); }
```

- [ ] **Step 4: Run the tests and confirm they pass.** `pytest tests/web -v` → 4 passed.

- [ ] **Step 5: Manual check.** Write the test's `BUNDLE` into `cache/bundles/`, run `telltale serve`, and open http://127.0.0.1:8000. The page should load and the slider should respond. Do the real visual pass after Integration I3.

- [ ] **Step 6: Enable JavaScript code scanning.** In `.github/workflows/security.yml`, change the CodeQL matrix to `language: [python, javascript-typescript]` (it was off until JS existed).

- [ ] **Step 7: Commit.** `git add telltale/web .github/workflows/security.yml && git commit -m "feat(web): timeline strip, verdict verification banner, replay UI"`

---

### Task D3: Docker image for the hosted demo

**Files:**
- Create: `Dockerfile`, `.dockerignore`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn telltale.web.app:app --host 0.0.0.0 --port ${PORT}"]
```

- [ ] **Step 2: Write `.dockerignore`**

```
.env
.git
vendor
data/nexar_raw
data/bench_clips
cache/sam_raw
cache/sam_bench
**/__pycache__
```

- [ ] **Step 3: Build and run (if Docker is installed).** `docker build -t telltale . && docker run -p 7860:7860 telltale`

- [ ] **Step 4: Commit.** `git add Dockerfile .dockerignore && git commit -m "chore: Docker image for hosted replay demo"`
