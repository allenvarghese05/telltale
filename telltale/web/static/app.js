/* Telltale replay.
   The clip plays, SAM's boxes track the vehicles, and each moment of the incident is revealed as the
   playhead reaches the timestamp it actually belongs to. The verdict lands when the clip ends.
   Every number here was computed in Python before this page was built; nothing is recomputed in JS. */

const $ = (id) => document.getElementById(id);

const LABELS = {
  PERCEPTION_LATE: 'The system detected the hazard late',
  COMMAND_LATE: 'Detected in time, but braking was commanded late',
  BRAKE_ACTUATION_LATE: 'The brakes built pressure too slowly',
  LATE_HANDOFF: 'Control was handed back too late for a human to react',
  UNAVOIDABLE: 'Physically unavoidable: a normal system would still have collided',
  NO_FAULT_FOUND: 'Avoidable, but no layer exceeded tolerance',
  INCONCLUSIVE: 'Inconclusive: the evidence is incomplete',
};

const SHORT = {
  PERCEPTION_LATE: 'Perception late',
  COMMAND_LATE: 'Command late',
  BRAKE_ACTUATION_LATE: 'Brake actuation late',
  LATE_HANDOFF: 'Late handoff',
  UNAVOIDABLE: 'Unavoidable',
  NO_FAULT_FOUND: 'No fault found',
  INCONCLUSIVE: 'Inconclusive',
};

/* The link in the chain each verdict blames. Used only to mark the timeline, never to compute anything. */
const FAILED_LINK = {
  PERCEPTION_LATE: 'AV:first_seen_t',
  COMMAND_LATE: 'AV:brake_request_t',
  BRAKE_ACTUATION_LATE: 'CAN:pressure_reached_t',
  LATE_HANDOFF: 'AV:handoff_t',
};

const PLOT_THEME = {
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  font: { color: '#a2a7b0', family: 'ui-monospace, SF Mono, Menlo, monospace', size: 10 },
};

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const num = (v, d = 2) => (Number.isFinite(Number(v)) ? Number(v).toFixed(d) : '-');

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

let cases = [];
let bundle = null;
let grid = null;
let events = [];
let failedKey = null;
let revealed = 0;
let landed = false;
let playing = false;

/* ---------- boot ---------- */

async function init() {
  try {
    cases = await getJSON('cases.json');
  } catch {
    $('run-note').textContent = 'No cases were exported. Run telltale analyze-all, then telltale export-site.';
    return;
  }
  if (!cases.length) {
    $('run-note').textContent = 'No cases were exported yet.';
    return;
  }
  const clips = [...new Set(cases.map((c) => c.clip_id))];
  $('clip').innerHTML = clips.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
  $('clip').onchange = selectClip;
  $('run').onclick = start;
  $('replay').onclick = start;
  $('skip').onclick = skipToVerdict;
  $('video').addEventListener('ended', land);
  requestAnimationFrame(frame);
  await selectClip();
}

async function selectClip() {
  const list = cases.filter((c) => c.clip_id === $('clip').value);
  await load(list[0].case_id);
  await renderVariants(list);
}

/* Every log variant's verdict for this clip, visible at once: the point is that one video supports
   several different causes depending on what the vehicle recorded. */
async function renderVariants(list) {
  const panel = $('variants-panel');
  panel.hidden = list.length < 2;
  if (list.length < 2) return;
  const loaded = await Promise.all(
    list.map(async (c) => {
      try {
        return { ...c, verdict: (await getJSON(`cases/${encodeURIComponent(c.case_id)}.json`)).verdict };
      } catch {
        return { ...c, verdict: null };
      }
    }),
  );
  $('variants').innerHTML = loaded
    .map((c, i) => {
      const v = c.verdict;
      const ok = v && v.status === 'VERIFIED';
      const label = v ? SHORT[v.agent_label] || v.agent_label : 'unavailable';
      const state = v ? (ok ? 'verified by recompute' : 'withheld, checker disagrees') : '';
      return `<button class="variant" data-id="${esc(c.case_id)}">
        <div class="variant-k">Log ${String.fromCharCode(65 + i)} / ${esc(c.profile)}</div>
        <div class="variant-v">${esc(label)}</div>
        <div class="variant-s ${ok ? 'ok' : 'no'}">${esc(state)}</div></button>`;
    })
    .join('');
  $('variants').querySelectorAll('.variant').forEach((b) => {
    b.onclick = async () => {
      await load(b.dataset.id);
      markActive();
      start();
    };
  });
  markActive();
}

function markActive() {
  $('variants')
    .querySelectorAll('.variant')
    .forEach((b) => b.classList.toggle('active', b.dataset.id === bundle.case_id));
}

/* ---------- one case ---------- */

async function load(id) {
  bundle = await getJSON(`cases/${encodeURIComponent(id)}.json`);
  try {
    grid = await getJSON(`cf/${encodeURIComponent(id)}.json`);
  } catch {
    grid = null;
  }
  events = [...(bundle.events || [])].sort((a, b) => a.t - b.t);
  failedKey = bundle.verdict && bundle.verdict.status === 'VERIFIED' ? FAILED_LINK[bundle.verdict.agent_label] : null;

  const video = $('video');
  if (video.getAttribute('src') !== bundle.video_url) video.src = bundle.video_url;
  reset();
  renderChain();
  renderClaims();
  renderTrace();
  drawTimeline();
  drawAvoidanceMap();
  $('report-link').href = `reports/${encodeURIComponent(id)}.html`;
  $('digest').textContent = bundle.digest || '-';
  renderSceneCaption();
  renderRunProvenance();
}

function reset() {
  revealed = 0;
  landed = false;
  playing = false;
  $('verdict').innerHTML = '';
  $('evidence').innerHTML = '';
  $('ledger-count').textContent = '';
  $('scrim').hidden = false;
  $('replay').hidden = true;
  $('skip').hidden = true;
  $('clock').textContent = '0.00 s';
  $('run-note').textContent = events.length
    ? `${events.length} recorded moments, ${(bundle.facts || []).length} evidence items`
    : 'This case has no timeline events.';
  const video = $('video');
  if (video.readyState) video.currentTime = 0;
}

function start() {
  reset();
  $('scrim').hidden = true;
  $('replay').hidden = false;
  $('skip').hidden = false;
  playing = true;
  const video = $('video');
  video.currentTime = 0;
  const attempt = video.play();
  if (attempt && attempt.catch) attempt.catch(() => skipToVerdict());
}

function skipToVerdict() {
  const video = $('video');
  video.pause();
  while (revealed < events.length) revealMoment(revealed);
  land();
}

/* ---------- the timeline chain ---------- */

function renderChain() {
  const chain = $('chain');
  if (!events.length) {
    chain.innerHTML = '';
    $('chain-caption').textContent = '';
    return;
  }
  const span = Math.max(events[events.length - 1].t - events[0].t, 0.001);
  const parts = [];
  events.forEach((e, i) => {
    if (i) {
      const d = e.t - events[i - 1].t;
      const bad = e.key === failedKey;
      parts.push(`<div class="gap ${bad ? 'bad' : ''}" data-i="${i}" data-d="${d}"
        style="flex-grow:${Math.max(d / span, 0.04)}"><span class="gap-v">+${num(d)} s</span></div>`);
    }
    const thumb = e.thumb
      ? `<img src="${esc(e.thumb)}" alt="">`
      : '<div class="noimg"></div>';
    parts.push(`<div class="moment ${e.key === failedKey ? 'failed' : ''}" data-i="${i}" data-t="${Number(e.t)}">
      ${thumb}<div class="moment-t">${num(e.t)} s</div>
      <div class="moment-l">${esc(e.label)}</div><div class="moment-s">${esc(e.source)}</div></div>`);
  });
  chain.innerHTML = parts.join('');
  chain.querySelectorAll('.moment').forEach((m) => {
    m.onclick = () => {
      $('video').currentTime = Number(m.dataset.t);
    };
  });
  $('chain-caption').textContent =
    'Gap widths are proportional to real elapsed time. Click any moment to jump the video there.';
}

function revealMoment(i) {
  const node = $('chain').querySelector(`.moment[data-i="${i}"]`);
  if (node) node.classList.add('reached');
  const gap = $('chain').querySelector(`.gap[data-i="${i}"]`);
  if (gap) {
    gap.classList.remove('counting');
    gap.querySelector('.gap-v').textContent = `+${num(gap.dataset.d)} s`;
  }
  addEvidenceFor(events[i]);
  revealed = Math.max(revealed, i + 1);
}

/* While waiting for the next moment, the elapsed gap counts up, so a late reaction is felt and not
   merely reported. */
function tickGap(now) {
  const gap = $('chain').querySelector(`.gap[data-i="${revealed}"]`);
  if (!gap || revealed === 0) return;
  const elapsed = now - events[revealed - 1].t;
  if (elapsed <= 0) return;
  gap.classList.add('counting');
  gap.querySelector('.gap-v').textContent = `+${num(elapsed)} s`;
}

/* ---------- evidence ledger ---------- */

function addEvidenceFor(event) {
  const fact = (bundle.facts || []).find((f) => f.id === event.key);
  appendFact(fact || { id: event.key, value: event.t, unit: 's', derivation: event.label });
}

function appendFact(fact) {
  const unit = fact.unit ? ` ${fact.unit}` : '';
  const li = document.createElement('li');
  li.innerHTML = `<div class="fact-id">${esc(fact.id)}</div>
    <div class="fact-v">${esc(fact.value)}${esc(unit)}</div>
    <div class="fact-d">${esc(fact.derivation || '')}</div>`;
  $('evidence').append(li);
  $('evidence').scrollTop = $('evidence').scrollHeight;
  $('ledger-count').textContent = `${$('evidence').children.length} items`;
}

/* After the clip ends, the rest of the evidence store is listed: thresholds, profile values and the
   facts the agent's own tools appended. */
function appendRemainingEvidence() {
  const shown = new Set(events.map((e) => e.key));
  (bundle.facts || []).filter((f) => !shown.has(f.id)).forEach(appendFact);
}

function renderSceneCaption() {
  const s = bundle.scene;
  if (!s) {
    $('scene-caption').textContent = '';
    return;
  }
  const bits = [];
  if (s.tracked_vehicles) bits.push(`${s.tracked_vehicles} vehicles tracked by SAM 3.1`);
  if (Array.isArray(s.hazards) && s.hazards.length) bits.push(`${s.hazards.length} became a hazard`);
  if (s.danger_onset_reason) bits.push(`onset by ${s.danger_onset_reason}`);
  const c = s.conditions || {};
  const seen = [c.weather, c.lighting, c.road_surface].filter(Boolean);
  if (seen.length) bits.push(`witness saw ${seen.join(', ')}`);
  $('scene-caption').textContent = bits.join(' / ');
}

function renderRunProvenance() {
  const agent = bundle.agent || {};
  const n = (agent.tool_calls || []).length;
  const stale = bundle.stale_agent_run
    ? ' This cached run predates the current evidence, so the checker treats it as stale.'
    : '';
  $('run-provenance').textContent =
    `Replay of a completed investigation: ${agent.model || 'unknown model'} reached this verdict in ` +
    `${n} tool call${n === 1 ? '' : 's'}. Each moment above appears at the video timestamp it belongs to.${stale}`;
}

/* ---------- playback ---------- */

function frame() {
  const video = $('video');
  if (bundle && playing) {
    const now = video.currentTime;
    $('clock').textContent = `${num(now)} s`;
    while (revealed < events.length && now >= events[revealed].t) revealMoment(revealed);
    tickGap(now);
    if (!landed && revealed >= events.length && video.ended) land();
  }
  drawOverlay();
  requestAnimationFrame(frame);
}

function drawOverlay() {
  const video = $('video');
  const canvas = $('overlay');
  if (!bundle || !video.clientWidth) return;
  if (canvas.width !== video.clientWidth || canvas.height !== video.clientHeight) {
    canvas.width = video.clientWidth;
    canvas.height = video.clientHeight;
  }
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const poly = bundle.lane_polygon || [];
  if (poly.length) {
    ctx.beginPath();
    poly.forEach(([x, y], i) =>
      i ? ctx.lineTo(x * canvas.width, y * canvas.height) : ctx.moveTo(x * canvas.width, y * canvas.height),
    );
    ctx.closePath();
    ctx.fillStyle = 'rgba(233,234,238,0.06)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(233,234,238,0.5)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  const boxes = bundle.target_boxes || [];
  if (!boxes.length || !bundle.fps) return;
  const f = Math.round(video.currentTime * bundle.fps);
  const nearest = boxes.reduce((a, b) => (Math.abs(b.frame - f) < Math.abs(a.frame - f) ? b : a));
  if (Math.abs(nearest.frame - f) > 2) return;
  const sx = canvas.width / bundle.width;
  const sy = canvas.height / bundle.height;
  const [l, t, r, b] = nearest.box;
  ctx.strokeStyle = revealed ? '#e4584f' : 'rgba(233,234,238,0.75)';
  ctx.lineWidth = 2;
  ctx.strokeRect(l * sx, t * sy, (r - l) * sx, (b - t) * sy);
  ctx.fillStyle = ctx.strokeStyle;
  ctx.font = '600 11px ui-monospace, SF Mono, Menlo, monospace';
  ctx.fillText('struck vehicle', l * sx, Math.max(t * sy - 5, 11));
}

/* ---------- verdict ---------- */

function land() {
  if (landed || !bundle) return;
  landed = true;
  playing = false;
  appendRemainingEvidence();
  const v = bundle.verdict || {};
  const ok = v.status === 'VERIFIED';
  const excess = v.excess_s || {};
  const worst = Object.entries(excess).sort((a, b) => b[1] - a[1])[0];
  const lateness = ok && worst ? `<div class="verdict-gap">${num(worst[1])} s beyond tolerance</div>` : '';
  const noncausal = (v.noncausal_faults || []).length
    ? `<p class="note">Faults present but not causal: ${esc(v.noncausal_faults.join(', '))}</p>`
    : '';
  const reason = v.reason ? `<p class="note">${esc(v.reason)}</p>` : '';

  $('verdict').innerHTML = `<div class="verdict-card ${ok ? 'ok' : 'rejected'}">
    <div class="verdict-k">${ok ? 'Primary contributing factor' : 'Verdict withheld pending human review'}</div>
    <div class="verdict-v">${esc(LABELS[v.agent_label] || v.agent_label || 'unavailable')}</div>
    ${lateness}
    <div class="readings">
      <div class="reading"><div class="reading-k">Muse Wonder concluded</div>
        <div class="reading-v">${esc(v.agent_label || '-')}</div></div>
      <div class="reading"><div class="reading-k">Python recomputed</div>
        <div class="reading-v">${esc(v.independent_label || '-')}</div></div>
      <div class="agreement ${ok ? 'ok' : 'no'}">${ok ? 'Independently verified' : 'The two disagree'}</div>
    </div>
    ${noncausal}${reason}</div>`;
}

/* ---------- charts ---------- */

function drawTimeline() {
  const series = bundle.series || {};
  const traces = [];
  const speed = series['can.speed_mps'];
  const brake = series['can.brake_pressure_kpa'];
  if (speed && speed.t && speed.t.length) {
    traces.push({
      x: speed.t,
      y: speed.v.map((x) => x * 3.6),
      name: 'Speed km/h',
      line: { color: '#e9eaee', width: 1.5 },
    });
  }
  if (brake && brake.t && brake.t.length) {
    traces.push({
      x: brake.t,
      y: brake.v,
      name: 'Brake pressure kPa',
      yaxis: 'y2',
      line: { color: '#58c08a', width: 1.5 },
    });
  }
  if (!traces.length) {
    $('timeline').innerHTML = '<p class="caption">No CAN series in this bundle.</p>';
    return;
  }
  const shapes = events.map((e) => ({
    type: 'line',
    x0: e.t,
    x1: e.t,
    yref: 'paper',
    y0: 0,
    y1: 1,
    line: { dash: 'dot', width: 1, color: e.key === failedKey ? '#e4584f' : 'rgba(255,255,255,0.25)' },
  }));
  Plotly.newPlot(
    'timeline',
    traces,
    {
      ...PLOT_THEME,
      height: 232,
      margin: { t: 8, b: 34, l: 44, r: 44 },
      xaxis: { title: 'video time (s)', gridcolor: 'rgba(255,255,255,0.06)', zeroline: false },
      yaxis: { title: 'km/h', gridcolor: 'rgba(255,255,255,0.06)', zeroline: false },
      yaxis2: { overlaying: 'y', side: 'right', title: 'kPa', showgrid: false, zeroline: false },
      shapes,
      showlegend: true,
      legend: { orientation: 'h', y: -0.32 },
    },
    { displayModeBar: false, responsive: true },
  );
  $('timeline').on('plotly_click', (ev) => {
    $('video').currentTime = ev.points[0].x;
  });
}

const nearestIndex = (values, x) =>
  values.reduce((best, v, i) => (Math.abs(v - x) < Math.abs(values[best] - x) ? i : best), 0);

function drawAvoidanceMap() {
  if (!grid) {
    $('cf-out').innerHTML = '<span class="caption">No avoidance map for this case.</span>';
    $('cf-map').innerHTML = '';
    return;
  }
  const m = grid.measured || {};
  const n = grid.nominal || {};
  const mp = nearestIndex(grid.perception_s, m.perception_s ?? n.perception_s);
  const mt = nearestIndex(grid.tau_s, m.tau_s ?? n.tau_s);
  const np = nearestIndex(grid.perception_s, n.perception_s);
  const nt = nearestIndex(grid.tau_s, n.tau_s);
  const at = (p, t) => grid.impact_kmh[p][t];
  const say = (p, t) =>
    at(p, t) > 0 ? `<b class="bad">collision at ${num(at(p, t), 1)} km/h</b>` : '<b class="good">avoided</b>';

  $('cf-out').innerHTML = `This vehicle, as it actually behaved: ${say(mp, mt)}.
    A system performing to spec: ${say(np, nt)}.`;

  Plotly.newPlot(
    'cf-map',
    [
      {
        type: 'heatmap',
        x: grid.tau_s,
        y: grid.perception_s,
        z: grid.impact_kmh,
        zmin: 0,
        colorscale: [
          [0, '#0b0c0e'],
          [0.01, '#2b1d1f'],
          [0.5, '#8c3b36'],
          [1, '#e4584f'],
        ],
        colorbar: { title: 'km/h', thickness: 10, len: 0.9 },
        hovertemplate: 'detection %{y:.2f} s, brake build-up %{x:.2f} s<br>impact %{z:.1f} km/h<extra></extra>',
      },
      {
        type: 'scatter',
        mode: 'markers+text',
        x: [grid.tau_s[mt]],
        y: [grid.perception_s[mp]],
        text: ['measured'],
        textposition: 'top right',
        textfont: { color: '#e9eaee', size: 10 },
        marker: { size: 11, symbol: 'circle', color: '#e9eaee', line: { width: 1.5, color: '#0b0c0e' } },
      },
      {
        type: 'scatter',
        mode: 'markers+text',
        x: [grid.tau_s[nt]],
        y: [grid.perception_s[np]],
        text: ['to spec'],
        textposition: 'bottom right',
        textfont: { color: '#58c08a', size: 10 },
        marker: { size: 11, symbol: 'diamond', color: '#58c08a', line: { width: 1.5, color: '#0b0c0e' } },
      },
    ],
    {
      ...PLOT_THEME,
      height: 320,
      margin: { t: 8, b: 42, l: 54, r: 10 },
      xaxis: { title: 'brake build-up time constant (s)', zeroline: false },
      yaxis: { title: 'detection delay (s)', zeroline: false },
      showlegend: false,
    },
    { displayModeBar: false, responsive: true },
  );
}

/* ---------- claims and trace ---------- */

function renderClaims() {
  const counts = bundle.counts || {};
  $('counts').textContent =
    `${counts.VERIFIED || 0} verified / ${counts.UNCORROBORATED || 0} single-source / ${counts.BLOCKED || 0} blocked`;
  const claims = bundle.claims || [];
  $('claim-list').innerHTML = claims.length
    ? claims
        .map((c) => {
          const claim = c.claim || {};
          const ev = (claim.evidence || []).map(esc).join(' / ');
          const why = (c.reasons || []).length ? `<div class="why">${(c.reasons || []).map(esc).join('<br>')}</div>` : '';
          return `<li class="${esc(c.status)}"><span class="chip">${esc(c.status)}</span>${esc(claim.text || '')}
            ${ev ? `<div class="ev">${ev}</div>` : ''}${why}</li>`;
        })
        .join('')
    : '<li class="caption">No claims in this bundle.</li>';
}

function renderTrace() {
  const agent = bundle.agent || {};
  const calls = agent.tool_calls || [];
  $('agent-meta').textContent = `${esc(agent.model || 'unknown')} / ${calls.length} tool calls`;
  $('trace-list').innerHTML = calls.length
    ? calls
        .map((t) => `<li><span class="tool">${esc(t.name)}</span> ${esc(JSON.stringify(t.args || {}))}</li>`)
        .join('')
    : '<li class="caption">No tool calls recorded.</li>';
}

init();
