/* Local upload page. Sends one clip to this machine's telltale upload-ui server and shows each step as it runs.
   The server validates everything again; these checks only save a round trip. */

const $ = (id) => document.getElementById(id);

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const SAFE_ID = /^[A-Za-z0-9_-]+$/;
const MAX_BYTES = 200 * 1024 * 1024;
const TYPES = { mp4: 'video/mp4', mov: 'video/quicktime' };

function fail(message) {
  $('alert').textContent = message;
  $('submit').disabled = false;
}

function renderSteps(steps) {
  $('steps').hidden = false;
  $('steps').innerHTML = steps.map((s) => `<li class="${esc(s.state)}">${esc(s.label)}</li>`).join('');
}

async function poll(clipId) {
  const r = await fetch(`/api/status?clip_id=${encodeURIComponent(clipId)}`);
  const s = await r.json();
  if (!r.ok) return fail(s.error || 'Could not read the upload status.');
  renderSteps(s.steps || []);
  if (s.state === 'running') return setTimeout(() => poll(clipId), 1000);
  if (s.state === 'error') return fail(s.message);
  $('done').href = s.link;
  $('done').hidden = false;
  $('submit').disabled = false;
}

$('form').onsubmit = async (event) => {
  event.preventDefault();
  $('alert').textContent = '';
  $('done').hidden = true;
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
