/* Telltale, video only.
   Clips with no vehicle logs: the footage, every SAM track, the moment the struck vehicle became a hazard, and
   the plain-English video report. Nothing here is a verdict, and nothing is computed: every number comes from
   the exported bundle, which Python wrote. */

const $ = (id) => document.getElementById(id);

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const num = (v, d = 2) => (Number.isFinite(Number(v)) ? Number(v).toFixed(d) : '-');

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

let clip = null;

async function init() {
  let index = [];
  try {
    index = await getJSON('videos.json');
  } catch {
    index = [];
  }
  if (!index.length) {
    $('play').hidden = true;
    $('scrim-note').textContent =
      'No video-only clips have been exported. Run telltale investigate-clip, then telltale export-site.';
    return;
  }
  $('clip').innerHTML = index.map((c) => `<option value="${esc(c.clip_id)}">${esc(c.clip_id)}</option>`).join('');
  $('clip').onchange = () => load($('clip').value);
  $('play').onclick = start;
  $('replay').onclick = start;
  $('video').addEventListener('ended', () => {
    $('replay').hidden = false;
  });
  requestAnimationFrame(frame);
  const wanted = new URLSearchParams(location.search).get('clip');
  const first = index.some((c) => c.clip_id === wanted) ? wanted : index[0].clip_id;
  $('clip').value = first;
  await load(first);
}

async function load(id) {
  clip = await getJSON(`video/${encodeURIComponent(id)}.json`);
  const video = $('video');
  if (video.getAttribute('src') !== clip.video_url) video.src = clip.video_url;
  $('scrim').hidden = false;
  $('replay').hidden = true;
  $('clock').textContent = '0.00 s';
  const r = clip.report || {};
  $('scrim-note').textContent = `${r.tracked_vehicles ?? 0} vehicles tracked`;
  renderFacts(r);
  const cross = clip.geometry === 'cross-path';
  $('geometry').hidden = !cross;
  $('geometry').textContent = cross
    ? "Cross-path crash: the vehicles' paths cross rather than follow one lane. Telltale's crash physics is " +
      'one-dimensional and covers forward conflicts only, so even with vehicle logs this clip could not be ' +
      'attributed. What the footage shows below still holds.'
    : '';
  renderTimeline(r);
  renderSummary(r);
}

function start() {
  $('scrim').hidden = true;
  $('replay').hidden = true;
  const video = $('video');
  video.currentTime = 0;
  const attempt = video.play();
  if (attempt && attempt.catch) attempt.catch(() => {
    $('scrim').hidden = false;
  });
}

/* ---------- what the footage shows ---------- */

function row(term, detail) {
  return `<dt>${esc(term)}</dt><dd>${detail}</dd>`;
}

function renderFacts(r) {
  const rows = [row('Vehicles tracked', esc(r.tracked_vehicles ?? 0))];
  if (r.struck_vehicle !== null && r.struck_vehicle !== undefined) {
    rows.push(row("Telltale's pick", `vehicle ${esc(r.struck_vehicle)}<span class="sub">the vehicle that was struck</span>`));
  }
  const onset = r.hazard_onset;
  rows.push(
    row(
      'Became a hazard',
      onset
        ? `${esc(num(onset.t))} s, ${esc(num(onset.warning_s))} s before impact<span class="sub">${esc(onset.how)}</span>`
        : "Telltale's pick never registered as a hazard.",
    ),
  );
  rows.push(row('Impact', `${esc(num(r.impact_t))} s<span class="sub">time given with the clip</span>`));
  const changes = r.struck_vehicle_lane_changes || [];
  rows.push(
    row(
      'Lane changes',
      changes.length
        ? changes
            .map((c) => `${esc(c.direction)}, ${esc(num(c.start_t))} to ${esc(num(c.end_t))} s`)
            .join('<br>')
        : "None detected for Telltale's pick.",
    ),
  );
  const others = r.other_hazards || [];
  if (others.length) rows.push(row('Other hazards', `${esc(others.length)} other vehicle(s)`));
  const c = r.conditions || {};
  const seen = [c.lighting, c.weather, c.road_surface && `${c.road_surface} road`].filter(Boolean);
  rows.push(row('Witness saw', seen.length ? esc(seen.join(', ')) : 'No witness answers for this clip.'));
  $('facts').innerHTML = rows.join('');
}

function renderTimeline(r) {
  const events = r.timeline || [];
  $('timeline').innerHTML = events.length
    ? events
        .map(
          (e) => `<li><button class="moment-row" data-t="${Number(e.t)}">
            <span class="moment-t">${esc(num(e.t))} s</span><span class="moment-l">${esc(e.event)}</span></button></li>`,
        )
        .join('')
    : '<li class="caption">No events were detected.</li>';
  $('timeline')
    .querySelectorAll('.moment-row')
    .forEach((b) => {
      b.onclick = () => {
        $('scrim').hidden = true;
        $('video').currentTime = Number(b.dataset.t);
      };
    });
}

function renderSummary(r) {
  const lines = (r.summary || []).map((s) => `<span class="sentence">${esc(s)}</span>`).join(' ');
  $('summary').innerHTML = `<p>${lines || 'No report for this clip.'}</p><p class="attribution">${esc(
    r.attribution || 'Cause not determined from video alone.',
  )}</p>`;
}

/* ---------- playback ---------- */

function frame() {
  const video = $('video');
  if (clip) {
    const now = video.currentTime;
    $('clock').textContent = `${num(now)} s`;
    $('timeline')
      .querySelectorAll('.moment-row')
      .forEach((b) => b.classList.toggle('reached', Number(b.dataset.t) <= now));
    drawOverlay(now);
  }
  requestAnimationFrame(frame);
}

function nearest(dets, f) {
  let best = null;
  for (const d of dets) if (!best || Math.abs(d[0] - f) < Math.abs(best[0] - f)) best = d;
  return best && Math.abs(best[0] - f) <= 2 ? best : null;
}

function drawOverlay(now) {
  const video = $('video');
  const canvas = $('overlay');
  if (!video.clientWidth || !clip.width) return;
  if (canvas.width !== video.clientWidth || canvas.height !== video.clientHeight) {
    canvas.width = video.clientWidth;
    canvas.height = video.clientHeight;
  }
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const poly = clip.lane_polygon || [];
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
  const f = Math.round(now * clip.fps);
  const sx = canvas.width / clip.width;
  const sy = canvas.height / clip.height;
  const r = clip.report || {};
  const struck = r.struck_vehicle;
  const hazard = r.hazard_onset && now >= r.hazard_onset.t;
  for (const [oid, dets] of Object.entries(clip.tracks || {})) {
    const d = nearest(dets, f);
    if (!d) continue;
    const [, l, t, rr, b] = d;
    const isStruck = oid === struck;
    ctx.lineWidth = isStruck ? 2 : 1;
    ctx.strokeStyle = isStruck ? (hazard ? '#ff453a' : 'rgba(255,255,255,0.95)') : 'rgba(255,255,255,0.4)';
    ctx.strokeRect(l * sx, t * sy, (rr - l) * sx, (b - t) * sy);
    if (isStruck) {
      ctx.fillStyle = ctx.strokeStyle;
      ctx.font = '600 12px -apple-system, BlinkMacSystemFont, Helvetica Neue, sans-serif';
      ctx.fillText(hazard ? "Telltale's pick: hazard" : "Telltale's pick", l * sx, Math.max(t * sy - 7, 13));
    }
  }
}

init();
