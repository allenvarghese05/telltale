/* Telltale replay.
   The clip plays, SAM's box tracks the struck vehicle, and each moment of the incident is revealed when the
   playhead reaches the timestamp it belongs to. The verdict lands when the clip ends, and the page closes on a
   plain-English report that Python wrote from the same facts. Nothing is computed here: every number on the
   page was produced in Python before the site was built. */

const $ = (id) => document.getElementById(id);

/* The export stamps a content build id on the page; every data and video URL carries it, so a new deploy is never
   served from a stale cache. */
const BUILD = (document.querySelector('meta[name="build"]') || {}).content || '';
const bust = (url) => (BUILD ? `${url}${url.includes('?') ? '&' : '?'}v=${BUILD}` : url);

const HEADLINE = {
  PERCEPTION_LATE: "The car's driver-assist noticed the hazard too late.",
  COMMAND_LATE: "The car's driver-assist noticed the hazard in time but commanded braking too late.",
  BRAKE_ACTUATION_LATE: 'The brakes built pressure too slowly.',
  LATE_HANDOFF: "The car's driver-assist handed control back too late for a person to react.",
  UNAVOIDABLE: 'Physically unavoidable. A driver-assist performing to spec would still have collided.',
  NO_FAULT_FOUND: 'Avoidable, but no step exceeded its limit.',
  INCONCLUSIVE: 'Inconclusive. The evidence is incomplete.',
};

const SHORT = {
  PERCEPTION_LATE: 'Noticed too late',
  COMMAND_LATE: 'Braking commanded late',
  BRAKE_ACTUATION_LATE: 'Brakes too slow',
  LATE_HANDOFF: 'Late handoff',
  UNAVOIDABLE: 'Unavoidable',
  NO_FAULT_FOUND: 'No step over its limit',
  INCONCLUSIVE: 'Inconclusive',
};

/* The link in the chain each verdict points at. Marks the timeline only; it computes nothing. */
const FAILED_LINK = {
  PERCEPTION_LATE: 'AV:first_seen_t',
  COMMAND_LATE: 'AV:brake_request_t',
  BRAKE_ACTUATION_LATE: 'CAN:pressure_reached_t',
  LATE_HANDOFF: 'AV:handoff_t',
};

const INK = '#1d1d1f';
const MUTE = '#6e6e73';
const OK = '#1f7a3f';
const PLOT = {
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  font: { color: MUTE, family: '-apple-system, BlinkMacSystemFont, Helvetica Neue, sans-serif', size: 11 },
};
const AXIS = { gridcolor: 'rgba(0,0,0,0.06)', zeroline: false, linecolor: 'rgba(0,0,0,0.16)' };

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const num = (v, d = 2) => (Number.isFinite(Number(v)) ? Number(v).toFixed(d) : '-');

async function getJSON(url) {
  const r = await fetch(bust(url));
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
    cases = [];
  }
  if (!cases.length) {
    $('run').hidden = true;
    $('run-note').textContent = 'No cases have been exported. Run telltale analyze-all, then telltale export-site.';
    return;
  }
  renderChooser();
  $('case').onchange = async () => {
    await load($('case').value);
    start();
  };
  $('watch').onclick = () => {
    document.querySelector('.chooser').scrollIntoView({ behavior: 'smooth', block: 'start' });
    start();
  };
  $('run').onclick = start;
  $('replay').onclick = start;
  $('skip').onclick = skipToVerdict;
  $('sources').onclick = toggleSources;
  $('full-investigation').addEventListener('toggle', () => {
    if ($('full-investigation').open) ['timeline', 'cf-map'].forEach((id) => window.Plotly && Plotly.Plots.resize(id));
  });
  $('video').addEventListener('ended', land);
  requestAnimationFrame(frame);
  await load($('case').value);
}

/* One chooser, in plain words: each crash is a group, each set of car logs an investigation titled by what the
   checker found. The titles are written by Python at export; the red-team case is grouped on its own. */
function renderChooser() {
  const groups = [];
  for (const c of cases) {
    const name = c.title.startsWith('Someone edits') ? 'Test the checker' : c.crash;
    let g = groups.find((x) => x.name === name);
    if (!g) groups.push((g = { name, items: [] }));
    g.items.push(c);
  }
  groups.sort((x, y) => (x.name === 'Test the checker') - (y.name === 'Test the checker'));
  $('case').innerHTML = groups
    .map(
      (g) => `<optgroup label="${esc(g.name)}">${g.items
        .map((c) => `<option value="${esc(c.case_id)}"${c.default ? ' selected' : ''}>${esc(c.title)}</option>`)
        .join('')}</optgroup>`,
    )
    .join('');
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
  if (video.getAttribute('src') !== bust(bundle.video_url)) video.src = bust(bundle.video_url);
  reset();
  renderChain();
  renderClaims();
  renderTrace();
  renderNarrative();
  drawTimeline();
  drawAvoidanceMap();
  $('report-link').href = `reports/${encodeURIComponent(id)}.html`;
  $('digest').textContent = bundle.digest || '-';
  renderSceneCaption();
  renderKeyFacts();
  renderRunProvenance();
}

function reset() {
  revealed = 0;
  landed = false;
  playing = false;
  $('verdict').innerHTML = '<p class="verdict-wait">The verdict appears when the replay ends.</p>';
  $('evidence').innerHTML = '<li class="caption ledger-empty">Evidence appears here as the replay reaches it.</li>';
  $('ledger-count').textContent = '';
  if (bundle) renderNarrative();
  $('scrim').hidden = false;
  $('replay').hidden = true;
  $('skip').hidden = true;
  $('clock').textContent = '0.00 s';
  $('run-note').textContent = bundle.red_team
    ? bundle.red_team
    : events.length
      ? `${events.length} moments, ${(bundle.facts || []).length} pieces of evidence`
      : 'This case has no timeline.';
  $('chain')
    .querySelectorAll('.reached')
    .forEach((n) => n.classList.remove('reached'));
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
  $('video').pause();
  $('scrim').hidden = true;
  while (revealed < events.length) revealMoment(revealed);
  land();
}

/* ---------- the latency chain ---------- */

function renderChain() {
  const chain = $('chain');
  if (!events.length) {
    chain.innerHTML = '';
    return;
  }
  const span = Math.max(events[events.length - 1].t - events[0].t, 0.001);
  chain.classList.toggle(
    'has-thumbs',
    events.some((e) => e.thumb),
  );
  chain.innerHTML = events
    .map((e, i) => {
      const gap = i
        ? `<div class="gap ${e.key === failedKey ? 'bad' : ''}" data-i="${i}" data-d="${e.t - events[i - 1].t}"
            style="flex-grow:${Math.max((e.t - events[i - 1].t) / span, 0.04)}">
            <span class="gap-v">+${num(e.t - events[i - 1].t)} s</span></div>`
        : '';
      const thumb = e.thumb ? `<img src="${esc(e.thumb)}" alt="">` : '';
      return `${gap}<button class="moment ${e.key === failedKey ? 'failed' : ''}" data-i="${i}" data-t="${Number(e.t)}"
        aria-label="${esc(e.label)} at ${num(e.t)} seconds">${thumb}
        <span class="moment-t">${num(e.t)} s</span><span class="moment-l">${esc(e.label)}</span>
        <span class="moment-s">${esc(e.source)}</span></button>`;
    })
    .join('');
  chain.querySelectorAll('.moment').forEach((m) => {
    m.onclick = () => {
      $('video').currentTime = Number(m.dataset.t);
    };
  });
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

/* While the next moment has not happened yet, its gap counts up, so a late reaction is felt as well as read. */
function tickGap(now) {
  if (revealed === 0) return;
  const gap = $('chain').querySelector(`.gap[data-i="${revealed}"]`);
  const elapsed = now - events[revealed - 1].t;
  if (!gap || elapsed <= 0) return;
  gap.classList.add('counting');
  gap.querySelector('.gap-v').textContent = `+${num(elapsed)} s`;
}

/* ---------- evidence ledger ---------- */

function addEvidenceFor(event) {
  const fact = (bundle.facts || []).find((f) => f.id === event.key);
  appendFact(fact || { id: event.key, value: event.t, unit: 's', derivation: event.label });
}

function appendFact(fact) {
  const empty = $('evidence').querySelector('.ledger-empty');
  if (empty) empty.remove();
  const li = document.createElement('li');
  li.innerHTML = `<div class="fact-id">${esc(fact.id)}</div>
    <div class="fact-v">${esc(fact.value)}${fact.unit ? ` ${esc(fact.unit)}` : ''}</div>
    <div class="fact-d">${esc(fact.derivation || '')}</div>`;
  $('evidence').append(li);
  $('evidence').scrollTop = $('evidence').scrollHeight;
  $('ledger-count').textContent = `${$('evidence').children.length}`;
}

/* Once the clip ends, the rest of the store follows: thresholds, witness answers, and the facts the
   investigator's own tools added. */
function appendRemainingEvidence() {
  const shown = new Set(events.map((e) => e.key));
  (bundle.facts || []).filter((f) => !shown.has(f.id)).forEach(appendFact);
}

function renderKeyFacts() {
  const s = bundle.scene || {};
  const c = s.conditions || {};
  const row = (k, v, sub = '') => `<dt>${esc(k)}</dt><dd>${v}${sub ? `<span class="sub">${esc(sub)}</span>` : ''}</dd>`;
  const rows = [row('Vehicle', esc(bundle.profile === 'truck' ? 'Loaded truck' : 'Car'))];
  if (s.tracked_vehicles) rows.push(row('Vehicles tracked', esc(s.tracked_vehicles)));
  if (s.target_object_id !== undefined && s.target_object_id !== null) {
    rows.push(row("Telltale's pick", `vehicle ${esc(s.target_object_id)}`, 'the vehicle that was struck'));
  }
  if (s.danger_onset_t !== undefined && s.danger_onset_t !== null) {
    rows.push(row('Became a hazard', `${esc(num(s.danger_onset_t))} s`, ONSET_HOW[s.danger_onset_reason] || ''));
  }
  const impact = factValue('VID:impact_t');
  if (impact !== undefined) rows.push(row('Impact', `${esc(num(impact))} s`));
  const seen = [c.lighting, c.weather, c.road_surface && `${c.road_surface} road`].filter((x) => x && x !== 'unclear');
  if (seen.length) rows.push(row('Witness saw', esc(seen.join(', '))));
  $('key-facts').innerHTML = rows.join('');
}

function renderSceneCaption() {
  const s = bundle.scene || {};
  const bits = [];
  if (s.tracked_vehicles) bits.push(`${s.tracked_vehicles} vehicles tracked`);
  if (Array.isArray(s.hazards) && s.hazards.length) bits.push(`${s.hazards.length} became hazards`);
  const c = s.conditions || {};
  const seen = [c.lighting, c.weather, c.road_surface].filter((x) => x && x !== 'unclear');
  if (seen.length) bits.push(`Witness saw ${seen.join(', ')}`);
  $('scene-caption').textContent = bits.length ? `${bits.join('. ')}.` : '';
}

function renderRunProvenance() {
  const agent = bundle.agent || {};
  const n = (agent.tool_calls || []).length;
  const stale = bundle.stale_agent_run ? ' This cached run predates the current evidence.' : '';
  $('run-provenance').textContent =
    `Replay of a completed investigation by ${agent.model || 'an unknown model'} in ${n} tool ` +
    `call${n === 1 ? '' : 's'}. Each moment appears at the video time it belongs to.${stale}`;
}

/* ---------- playback ---------- */

function frame() {
  const video = $('video');
  if (bundle && playing) {
    const now = video.currentTime;
    $('clock').textContent = `${num(now)} s`;
    while (revealed < events.length && now >= events[revealed].t) revealMoment(revealed);
    revealNarrative(now);
    tickGap(now);
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
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.65)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
  const boxes = bundle.target_boxes || [];
  if (!boxes.length || !bundle.fps || !bundle.width) return;
  const f = Math.round(video.currentTime * bundle.fps);
  const nearest = boxes.reduce((a, b) => (Math.abs(b.frame - f) < Math.abs(a.frame - f) ? b : a));
  if (Math.abs(nearest.frame - f) > 2) return;
  const sx = canvas.width / bundle.width;
  const sy = canvas.height / bundle.height;
  const [l, t, r, b] = nearest.box;
  const hazard = revealed > 0;
  ctx.strokeStyle = hazard ? '#ff453a' : 'rgba(255,255,255,0.9)';
  ctx.lineWidth = 2;
  ctx.strokeRect(l * sx, t * sy, (r - l) * sx, (b - t) * sy);
  ctx.fillStyle = ctx.strokeStyle;
  ctx.font = '600 12px -apple-system, BlinkMacSystemFont, Helvetica Neue, sans-serif';
  ctx.fillText(hazard ? 'Hazard' : 'Tracked vehicle', l * sx, Math.max(t * sy - 7, 13));
}

/* ---------- verdict ---------- */

/* What each verdict points at, for the at-a-glance numbers. Labels only: every value shown comes from the
   bundle's facts, the verdict's overruns, or the avoidance map's Python-computed outcomes. */
const STEP = {
  PERCEPTION_LATE: { name: 'Noticing the hazard', layer: 'perception', measured: 'PHYS:perception_latency_s', limit: 'PROFILE:perception_threshold_s', took: 'Took to notice', allowed: 'Allowed' },
  COMMAND_LATE: { name: 'Commanding the brakes', layer: 'command', measured: 'PHYS:command_latency_s', limit: 'PROFILE:command_threshold_s', took: 'Took to command', allowed: 'Allowed' },
  BRAKE_ACTUATION_LATE: { name: 'Building brake pressure', layer: 'actuation', measured: 'PHYS:actuation_latency_s', limit: 'PROFILE:actuation_threshold_s', took: 'Took to engage', allowed: 'Allowed' },
  LATE_HANDOFF: { name: 'Handing control back', layer: 'handoff', measured: 'PHYS:handoff_margin_s', limit: 'PROFILE:human_prt_s', took: 'Driver was given', allowed: 'A person needs' },
};

const ONSET_HOW = {
  entering: 'moved into the lane',
  predicted: 'about to cross into the lane',
  closing: 'already in the lane, closing',
};

const factValue = (id) => {
  const f = (bundle.facts || []).find((x) => x.id === id);
  return f ? f.value : undefined;
};

function stat(k, v, cls = '') {
  return `<div class="glance-item ${cls}"><div class="glance-k">${esc(k)}</div><div class="glance-v">${v}</div></div>`;
}

function glance(v) {
  const items = [];
  const step = STEP[v.independent_label];
  if (step) {
    items.push(stat('Failing step', esc(step.name)));
    const measured = factValue(step.measured);
    const limit = factValue(step.limit);
    if (measured !== undefined) items.push(stat(step.took, `${esc(num(measured))} s`));
    if (limit !== undefined) items.push(stat(step.allowed, `${esc(num(limit))} s`));
    const over = (v.excess_s || {})[step.layer];
    if (over !== undefined && over > 0) items.push(stat('Over by', `${esc(num(over))} s`, 'bad'));
  } else {
    items.push(stat('Failing step', 'None over its limit'));
  }
  const out = (grid && grid.outcome_kmh) || {};
  const say = (x) => (x > 0 ? `collides at ${esc(num(x, 1))} km/h` : 'avoids it');
  if (out.measured !== undefined && out.measured !== null) items.push(stat('As it happened', say(out.measured), out.measured > 0 ? 'bad' : 'good'));
  if (out.nominal !== undefined && out.nominal !== null) items.push(stat('Performing to spec', say(out.nominal), out.nominal > 0 ? 'bad' : 'good'));
  return `<div class="glance">${items.join('')}</div>`;
}

function card(actor, role, rows, cls = '') {
  const body = rows
    .filter(Boolean)
    .map(([k, val]) => `<div class="actor-row"><span class="actor-k">${esc(k)}</span><span class="actor-v">${val}</span></div>`)
    .join('');
  return `<article class="actor ${cls}"><h3>${esc(actor)}</h3><p class="actor-role">${esc(role)}</p>${body}</article>`;
}

function actors(v, ok) {
  const s = bundle.scene || {};
  const c = s.conditions || {};
  const counts = bundle.counts || {};
  const agent = bundle.agent || {};
  const seen = [c.lighting, c.weather, c.road_surface && `${c.road_surface} road`].filter((x) => x && x !== 'unclear');
  const rechecks = (bundle.facts || []).filter((f) => f.id.startsWith('WIT2:'));
  const onset = s.danger_onset_t !== undefined && s.danger_onset_t !== null
    ? `${esc(num(s.danger_onset_t))} s, ${esc(ONSET_HOW[s.danger_onset_reason] || s.danger_onset_reason || '')}`
    : 'not registered';
  const sam = card('SAM 3.1', 'Tracked every vehicle in the footage', [
    ['Vehicles tracked', esc(s.tracked_vehicles ?? '-')],
    s.target_object_id !== undefined && s.target_object_id !== null && ["Telltale's pick", `vehicle ${esc(s.target_object_id)}`],
    ['Became a hazard', onset],
  ]);
  const spark = card('Muse Spark 1.3', 'Watched the clip as an independent witness', [
    ['Conditions', seen.length ? esc(seen.join(', ')) : 'none reported'],
    ...rechecks.map((f) => [`Recheck: ${f.id.slice(5).replace(/_/g, ' ')}`, esc(f.value)]),
  ]);
  const wonder = card('Muse Wonder', 'Investigated the logs and decided the cause', [
    ['Its verdict', `<span class="label">${esc(SHORT[v.agent_label] || v.agent_label || '-')}</span>`],
    ['Tool calls', esc((agent.tool_calls || []).length)],
    ['Claims made', esc((bundle.claims || []).length)],
  ], ok ? 'agree' : 'disagree');
  const checker = card('Python checker', 'Recomputed every claim and the verdict, no model involved', [
    ['Its verdict', `<span class="label">${esc(SHORT[v.independent_label] || v.independent_label || '-')}</span>`],
    ['Claims', `${esc(counts.VERIFIED || 0)} verified, ${esc(counts.UNCORROBORATED || 0)} single-source, ${esc(counts.BLOCKED || 0)} blocked`],
    ['Outcome', ok ? '<span class="good">Verified, report released</span>' : '<span class="no">Withheld for human review</span>'],
  ], ok ? 'agree' : 'disagree');
  const link = ok
    ? 'Muse Wonder and the Python checker reached the same verdict independently.'
    : `They disagree: Muse Wonder said ${SHORT[v.agent_label] || v.agent_label}, the checker recomputed ${SHORT[v.independent_label] || v.independent_label}. The verdict is withheld.`;
  return `<h3 class="actors-title">Who said what</h3>
    <div class="actors">${sam}${spark}${wonder}${checker}</div>
    <p class="agreement-line ${ok ? 'good' : 'no'}">${esc(link)}</p>`;
}

function land() {
  if (landed || !bundle) return;
  landed = true;
  playing = false;
  $('skip').hidden = true;
  appendRemainingEvidence();
  revealNarrative(Infinity);
  const v = bundle.verdict || {};
  const ok = v.status === 'VERIFIED';
  const others = (v.noncausal_faults || []).length
    ? `<p class="verdict-note">Also outside its limit, but it would not have changed the outcome: ${esc(v.noncausal_faults.join(', '))}.</p>`
    : '';
  const headline = ok
    ? HEADLINE[v.agent_label] || v.agent_label
    : 'The investigator and the independent recomputation disagree.';
  const redTeam = bundle.red_team ? `<p class="red-team-note">${esc(bundle.red_team)}</p>` : '';
  $('verdict').innerHTML = `<div class="verdict-body">
    ${redTeam}
    <p class="verdict-state ${ok ? 'ok' : 'no'}">${ok ? 'Independently verified' : 'Withheld for human review'}</p>
    <h2 class="verdict-headline">${esc(headline || 'No verdict in this case.')}</h2>
    ${glance(v)}
    ${others}
    ${actors(v, ok)}</div>`;
}

/* ---------- charts ---------- */

function drawTimeline() {
  const s = bundle.series || {};
  const traces = [];
  const speed = s['can.speed_mps'];
  const brake = s['can.brake_pressure_kpa'];
  if (speed && speed.t && speed.t.length) {
    traces.push({ x: speed.t, y: speed.v.map((x) => x * 3.6), name: 'Speed (km/h)', line: { color: INK, width: 1.75 } });
  }
  if (brake && brake.t && brake.t.length) {
    traces.push({
      x: brake.t,
      y: brake.v,
      name: 'Brake pressure (kPa)',
      yaxis: 'y2',
      line: { color: MUTE, width: 1.5, dash: 'dot' },
    });
  }
  if (!traces.length) {
    $('timeline').innerHTML = '<p class="caption">This case has no CAN series.</p>';
    return;
  }
  const shapes = events.map((e) => ({
    type: 'line',
    x0: e.t,
    x1: e.t,
    yref: 'paper',
    y0: 0,
    y1: 1,
    line: { width: 1, color: e.key === failedKey ? '#c9341f' : 'rgba(0,0,0,0.14)' },
  }));
  Plotly.newPlot(
    'timeline',
    traces,
    {
      ...PLOT,
      height: 260,
      margin: { t: 16, b: 40, l: 48, r: 56 },
      xaxis: { ...AXIS, title: { text: 'Video time (s)' } },
      yaxis: { ...AXIS, title: { text: 'km/h' } },
      yaxis2: { overlaying: 'y', side: 'right', title: { text: 'kPa' }, showgrid: false, zeroline: false },
      shapes,
      legend: { orientation: 'h', x: 0, y: 1.14 },
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
    $('cf-out').textContent = 'This case has no avoidance map.';
    $('cf-map').innerHTML = '';
    return;
  }
  const m = grid.measured || {};
  const n = grid.nominal || {};
  const mp = nearestIndex(grid.perception_s, m.perception_s ?? n.perception_s);
  const mt = nearestIndex(grid.tau_s, m.tau_s ?? n.tau_s);
  const np = nearestIndex(grid.perception_s, n.perception_s);
  const nt = nearestIndex(grid.tau_s, n.tau_s);
  /* The sentence states the checker's exact replays, which the incident report also uses. The map's markers sit
     on the nearest sampled cell, which can differ slightly; a missing exact value falls back to that cell. */
  const exact = grid.outcome_kmh || {};
  const kmh = (value, p, t) => (value ?? grid.impact_kmh[p][t]);
  const say = (v) => (v > 0 ? `<b class="bad">collides at ${num(v, 1)} km/h</b>` : '<b class="good">avoids it</b>');
  $('cf-out').innerHTML = `As measured, this vehicle ${say(kmh(exact.measured, mp, mt))}. ` +
    `Performing to specification, it ${say(kmh(exact.nominal, np, nt))}.`;
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
          [0, '#f2f2f4'],
          [0.001, '#fbe7e3'],
          [0.55, '#efa496'],
          [1, '#c9341f'],
        ],
        colorbar: { title: { text: 'km/h' }, thickness: 8, len: 0.85, outlinewidth: 0 },
        hovertemplate: 'Noticed after %{y:.2f} s, brakes build in %{x:.2f} s<br>Impact %{z:.1f} km/h<extra></extra>',
      },
      {
        type: 'scatter',
        mode: 'markers+text',
        x: [grid.tau_s[mt]],
        y: [grid.perception_s[mp]],
        text: ['Measured'],
        textposition: 'middle right',
        textfont: { color: INK, size: 12 },
        marker: { size: 11, color: INK, line: { width: 2, color: '#fff' } },
      },
      {
        type: 'scatter',
        mode: 'markers+text',
        x: [grid.tau_s[nt]],
        y: [grid.perception_s[np]],
        text: ['To spec'],
        textposition: 'middle right',
        textfont: { color: OK, size: 12 },
        marker: { size: 11, symbol: 'diamond', color: OK, line: { width: 2, color: '#fff' } },
      },
    ],
    {
      ...PLOT,
      height: 380,
      margin: { t: 12, b: 48, l: 56, r: 12 },
      xaxis: { ...AXIS, title: { text: 'Brake build-up time constant (s)' } },
      yaxis: { ...AXIS, title: { text: 'Time to notice the vehicle (s)' } },
      showlegend: false,
    },
    { displayModeBar: false, responsive: true },
  );
}

/* ---------- claims, trace, report ---------- */

function renderClaims() {
  const c = bundle.counts || {};
  $('counts').textContent = `${c.VERIFIED || 0} verified, ${c.UNCORROBORATED || 0} single-source, ${c.BLOCKED || 0} blocked`;
  const claims = bundle.claims || [];
  const label = { VERIFIED: 'Verified', UNCORROBORATED: 'Single source', BLOCKED: 'Blocked' };
  $('claim-list').innerHTML = claims.length
    ? claims
        .map((r) => {
          const claim = r.claim || {};
          const ev = (claim.evidence || []).map(esc).join(', ');
          const why = (r.reasons || []).map(esc).join('. ');
          return `<li class="${esc(r.status)}"><span class="status ${esc(r.status)}">${esc(label[r.status] || r.status)}</span>
            <span class="claim-text">${esc(claim.text || '')}</span>
            ${ev ? `<span class="ev">${ev}</span>` : ''}${why ? `<span class="why">${why}</span>` : ''}</li>`;
        })
        .join('')
    : '<li class="caption">This case has no claims.</li>';
}

function renderTrace() {
  const agent = bundle.agent || {};
  const calls = agent.tool_calls || [];
  $('agent-meta').textContent = `${agent.model || 'unknown model'}, ${calls.length} calls`;
  $('trace-list').innerHTML = calls.length
    ? calls
        .map((t) => `<li><span><span class="tool">${esc(t.name)}</span><span class="args">${esc(JSON.stringify(t.args || {}))}</span></span></li>`)
        .join('')
    : '<li class="caption">No tool calls were recorded.</li>';
}

/* The report is text Python wrote. Each sentence keeps its sources, shown on request. */
/* The incident report writes itself during the replay. Each sentence appears when the playhead reaches the time
   of the event it cites (its own sources say which); sentences about the whole case appear with the verdict. The
   text is Python's; JS only decides when to show it. */
const TIMED = /^(VID|AV|CAN):[a-z_]+_t$/;

function revealTime(line, sectionIndex) {
  const times = (line.sources || []).filter((id) => TIMED.test(id)).map(factValue).filter((t) => Number.isFinite(Number(t)));
  if (times.length) return Math.max(...times.map(Number));
  return sectionIndex < 2 ? 0 : Infinity;
}

function renderNarrative() {
  const sections = bundle.narrative || [];
  $('report-wait').hidden = !sections.length;
  $('narrative').innerHTML = sections.length
    ? sections
        .map(
          (s, i) => `<section class="pending"><h3>${esc(s.title)}</h3><p>${(s.sentences || [])
            .map((line) => {
              const src = (line.sources || []).join(', ');
              const at = revealTime(line, i);
              return `<span class="sentence pending" data-at="${Number.isFinite(at) ? at : 'end'}"${
                src ? ` title="${esc(src)}"` : ''
              }>${esc(line.text)}${src ? `<span class="src"> [${esc(src)}]</span>` : ''}</span>`;
            })
            .join(' ')}</p></section>`,
        )
        .join('')
    : '<p class="caption">This case has no incident report. Re-export the site to generate one.</p>';
}

function revealNarrative(now) {
  let shown = false;
  $('narrative')
    .querySelectorAll('.sentence.pending')
    .forEach((el) => {
      const at = el.dataset.at;
      if (at === 'end' ? now !== Infinity : Number(at) > now) return;
      el.classList.remove('pending');
      el.closest('section').classList.remove('pending');
      shown = true;
    });
  if (shown) {
    $('report-wait').hidden = true;
    const box = $('narrative');
    box.scrollTop = box.scrollHeight;
  }
}

function toggleSources() {
  const on = !$('narrative').classList.contains('show-sources');
  $('narrative').classList.toggle('show-sources', on);
  $('sources').setAttribute('aria-pressed', String(on));
  $('sources').textContent = on ? 'Hide sources' : 'Show sources';
}

init();
