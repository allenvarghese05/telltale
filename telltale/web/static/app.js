/* Telltale replay.
   The clip plays, SAM's box tracks the struck vehicle, and each moment of the incident is revealed when the
   playhead reaches the timestamp it belongs to. The verdict lands when the clip ends, and the page closes on a
   plain-English report that Python wrote from the same facts. Nothing is computed here: every number on the
   page was produced in Python before the site was built. */

const $ = (id) => document.getElementById(id);

const HEADLINE = {
  PERCEPTION_LATE: 'The system noticed the hazard too late.',
  COMMAND_LATE: 'The hazard was noticed in time. Braking was commanded too late.',
  BRAKE_ACTUATION_LATE: 'The brakes built pressure too slowly.',
  LATE_HANDOFF: 'Control was handed back too late for a person to react.',
  UNAVOIDABLE: 'Physically unavoidable. A system performing to spec would still have collided.',
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
    cases = [];
  }
  if (!cases.length) {
    $('run').hidden = true;
    $('run-note').textContent = 'No cases have been exported. Run telltale analyze-all, then telltale export-site.';
    return;
  }
  const clips = [...new Set(cases.map((c) => c.clip_id))];
  $('clip').innerHTML = clips.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
  $('clip').onchange = selectClip;
  $('run').onclick = start;
  $('replay').onclick = start;
  $('skip').onclick = skipToVerdict;
  $('sources').onclick = toggleSources;
  $('video').addEventListener('ended', land);
  requestAnimationFrame(frame);
  await selectClip();
}

async function selectClip() {
  const list = cases.filter((c) => c.clip_id === $('clip').value);
  await load(list[0].case_id);
  await renderVariants(list);
}

/* Every log variant's verdict for this clip, side by side: one video, several possible causes. */
async function renderVariants(list) {
  $('variants-panel').hidden = list.length < 2;
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
      const label = v ? SHORT[v.agent_label] || v.agent_label : 'Unavailable';
      const state = v ? (ok ? 'Verified by recomputation' : 'Withheld. The checker disagrees.') : '';
      return `<button class="variant" data-id="${esc(c.case_id)}">
        <span class="variant-k">Log ${String.fromCharCode(65 + i)}, ${esc(c.profile)}</span>
        <span class="variant-v">${esc(label)}</span>
        <span class="variant-s ${ok ? 'ok' : 'no'}">${esc(state)}</span></button>`;
    })
    .join('');
  $('variants')
    .querySelectorAll('.variant')
    .forEach((b) => {
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
  renderNarrative();
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
  $('verdict').innerHTML = '<p class="verdict-wait">The verdict appears when the replay ends.</p>';
  $('evidence').innerHTML = '<li class="caption ledger-empty">Evidence appears here as the replay reaches it.</li>';
  $('ledger-count').textContent = '';
  $('scrim').hidden = false;
  $('replay').hidden = true;
  $('skip').hidden = true;
  $('clock').textContent = '0.00 s';
  $('run-note').textContent = events.length
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

function land() {
  if (landed || !bundle) return;
  landed = true;
  playing = false;
  $('skip').hidden = true;
  appendRemainingEvidence();
  const v = bundle.verdict || {};
  const ok = v.status === 'VERIFIED';
  const worst = Object.entries(v.excess_s || {}).sort((a, b) => b[1] - a[1])[0];
  const over = ok && worst && worst[1] > 0 ? `<p class="verdict-over">${num(worst[1])} s past its limit</p>` : '';
  const others = (v.noncausal_faults || []).length
    ? `<p class="verdict-note">Also outside its limit, but it would not have changed the outcome: ${esc(v.noncausal_faults.join(', '))}.</p>`
    : '';
  const headline = ok
    ? HEADLINE[v.agent_label] || v.agent_label
    : 'The investigator and the independent recomputation disagree.';
  $('verdict').innerHTML = `<div class="verdict-body">
    <p class="verdict-state ${ok ? 'ok' : 'no'}">${ok ? 'Independently verified' : 'Withheld for human review'}</p>
    <h2 class="verdict-headline">${esc(headline || 'No verdict in this case.')}</h2>
    ${over}
    <div class="readings">
      <div><div class="reading-k">Muse Wonder concluded</div><div class="reading-v">${esc(v.agent_label || '-')}</div></div>
      <div><div class="reading-k">Python recomputed</div><div class="reading-v">${esc(v.independent_label || '-')}</div></div>
    </div>
    ${others}</div>`;
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
  const at = (p, t) => grid.impact_kmh[p][t];
  const say = (p, t) =>
    at(p, t) > 0 ? `<b class="bad">collides at ${num(at(p, t), 1)} km/h</b>` : '<b class="good">avoids it</b>';
  $('cf-out').innerHTML = `As measured, this vehicle ${say(mp, mt)}. Performing to specification, it ${say(np, nt)}.`;
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
function renderNarrative() {
  const sections = bundle.narrative || [];
  $('narrative').innerHTML = sections.length
    ? sections
        .map(
          (s) => `<h3>${esc(s.title)}</h3><p>${(s.sentences || [])
            .map((line) => {
              const src = (line.sources || []).join(', ');
              return `<span class="sentence"${src ? ` title="${esc(src)}"` : ''}>${esc(line.text)}</span>${
                src ? `<span class="src">[${esc(src)}]</span>` : ''
              }`;
            })
            .join(' ')}</p>`,
        )
        .join('')
    : '<p class="caption">This case has no incident report. Re-export the site to generate one.</p>';
}

function toggleSources() {
  const on = !$('narrative').classList.contains('show-sources');
  $('narrative').classList.toggle('show-sources', on);
  $('sources').setAttribute('aria-pressed', String(on));
  $('sources').textContent = on ? 'Hide sources' : 'Show sources';
}

init();
