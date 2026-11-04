/* Local upload page. Sends one clip to this machine's telltale upload-ui server, shows each step as it runs with
   what it is doing and how long it usually takes, then shows the finished clip inline.
   The server validates everything again; these checks only save a round trip. */

const $ = (id) => document.getElementById(id);

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const SAFE_ID = /^[A-Za-z0-9_-]+$/;
const MAX_BYTES = 200 * 1024 * 1024;
const TYPES = { mp4: 'video/mp4', mov: 'video/quicktime' };

/* What each step is doing, and roughly how long it takes, so a long SAM run never looks stuck. */
const DETAIL = {
  prepare: { what: 'Re-encoding to H.264 and registering the clip on this computer.', expect: 'a few seconds' },
  track: { what: "SAM 3.1 tracks every vehicle frame by frame on Meta's API.", expect: 'usually 1 to 2 min' },
  witness: { what: 'Muse Spark watches the clip and describes the conditions.', expect: 'about 30 s' },
  report: { what: 'Building the video-only report and adding it to the site.', expect: 'a few seconds' },
};

let activeKey = null;
let activeSince = 0;
let tick = null;
let lastSteps = [];

function fail(message) {
  $('alert').textContent = message;
  $('submit').disabled = false;
  clearInterval(tick);
}

function elapsed() {
  const s = Math.floor((Date.now() - activeSince) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function renderSteps(steps) {
  lastSteps = steps;
  const active = steps.find((s) => s.state === 'active');
  if (active && active.key !== activeKey) {
    activeKey = active.key;
    activeSince = Date.now();
  }
  $('progress').hidden = false;
  $('steps').innerHTML = steps
    .map((s) => {
      const d = DETAIL[s.key] || { what: '', expect: '' };
      const time = s.state === 'active' ? `${elapsed()} of ${d.expect}` : s.state === 'done' ? 'done' : d.expect;
      return `<li class="${esc(s.state)}"><span class="dot" aria-hidden="true"></span>
        <span class="label">${esc(s.label)}</span><span class="time">${esc(time)}</span>
        <span class="what">${esc(d.what)}</span></li>`;
    })
    .join('');
}

function showResult(clipId, link) {
  const frame = $('result-frame');
  frame.onload = () => {
    frame.style.height = `${frame.contentDocument.documentElement.scrollHeight + 24}px`;
  };
  frame.src = `${link}&embed=1`;
  $('result-link').href = link;
  $('result-title').textContent = `Your clip: ${clipId}`;
  $('result').hidden = false;
  $('result').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function poll(clipId) {
  const r = await fetch(`/api/status?clip_id=${encodeURIComponent(clipId)}`);
  const s = await r.json();
  if (!r.ok) return fail(s.error || 'Could not read the upload status.');
  renderSteps(s.steps || []);
  if (s.state === 'running') return setTimeout(() => poll(clipId), 1000);
  clearInterval(tick);
  if (s.state === 'error') return fail(s.message);
  $('submit').disabled = false;
  showResult(clipId, s.link);
}

/* A suggested impact time from the camera jolt, for the person to check. Close to the human label on about two
   clips in three, so it is shown as a pre-filled, editable value, never used without them seeing it. */
$('file').onchange = async () => {
  const file = $('file').files[0];
  const ext = file ? file.name.split('.').pop().toLowerCase() : '';
  if (!file || !TYPES[ext] || file.size > MAX_BYTES) return;
  $('impact-help').textContent = 'Finding a suggested impact time from the camera jolt...';
  const r = await fetch('/api/suggest', {
    method: 'POST',
    headers: { 'Content-Type': TYPES[ext], 'X-Filename': `clip.${ext}` },
    body: file,
  });
  const body = await r.json();
  if (r.ok && Number.isFinite(body.suggested_t)) {
    $('impact').value = body.suggested_t.toFixed(2);
    $('impact-help').textContent =
      `Suggested from the camera jolt: ${body.suggested_t.toFixed(2)} s. Please check it in your player and correct ` +
      'it if needed; about a third of clips are off by more than a second.';
  } else {
    $('impact-help').textContent =
      'No suggestion for this clip. Type the time of impact, in seconds from the start of the video.';
  }
};

$('form').onsubmit = async (event) => {
  event.preventDefault();
  $('alert').textContent = '';
  $('result').hidden = true;
  const file = $('file').files[0];
  const clipId = $('clip-id').value.trim();
  const impact = $('impact').value.trim();
  const ext = file ? file.name.split('.').pop().toLowerCase() : '';
  if (!file) return fail('Choose a video file.');
  if (!TYPES[ext]) return fail('Upload an .mp4 or .mov file.');
  if (file.size > MAX_BYTES) return fail('That file is over 200 MB. Trim the clip first.');
  if (!SAFE_ID.test(clipId)) return fail('Use only letters, digits, hyphens and underscores for the clip id.');
  if (impact === '' || !Number.isFinite(Number(impact))) return fail('Impact time must be a number of seconds.');
  $('submit').disabled = true;
  activeKey = null;
  clearInterval(tick);
  tick = setInterval(() => renderSteps(lastSteps), 1000);
  const query = new URLSearchParams({ clip_id: clipId, impact_t: impact });
  const r = await fetch(`/api/upload?${query}`, {
    method: 'POST',
    headers: { 'Content-Type': TYPES[ext], 'X-Filename': `clip.${ext}` },
    body: file,
  });
  const body = await r.json();
  if (!r.ok) return fail(body.error || 'The upload was refused.');
  poll(clipId);
};
