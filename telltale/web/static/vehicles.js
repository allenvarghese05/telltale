/* Telltale: the vehicle layer of the replay overlay, shared by the investigated-crash and dashcam-clip pages.
   Every SAM-tracked vehicle is a faint box. Each turns amber from the moment it became a hazard, the struck
   vehicle is labelled, and at impact its box is emphasised. Drawing only: every time comes from the bundle. */

const VEHICLE_FONT = '600 12px -apple-system, BlinkMacSystemFont, Helvetica Neue, sans-serif';
const FAINT = 'rgba(255,255,255,0.35)';
const STRUCK = 'rgba(255,255,255,0.95)';
const AMBER = '#ffb020';
const IMPACT = '#ff453a';
const IMPACT_WINDOW_S = 0.4;

function nearestDetection(dets, frame) {
  let best = null;
  for (const d of dets) if (!best || Math.abs(d[0] - frame) < Math.abs(best[0] - frame)) best = d;
  return best && Math.abs(best[0] - frame) <= 2 ? best : null;
}

/* tracks: {id: [[frame, l, t, r, b], ...]} in source pixels; clip: {fps, width, height};
   scene: {struck, onsets: {id: seconds}, impactT}. */
function drawVehicles(ctx, canvas, tracks, clip, now, scene) {
  if (!tracks || !clip.fps || !clip.width) return;
  const frame = Math.round(now * clip.fps);
  const sx = canvas.width / clip.width;
  const sy = canvas.height / clip.height;
  const atImpact = scene.impactT != null && now >= scene.impactT - IMPACT_WINDOW_S;
  const ids = Object.keys(tracks).sort((a, b) => (a === scene.struck) - (b === scene.struck));
  for (const id of ids) {
    const d = nearestDetection(tracks[id], frame);
    if (!d) continue;
    const [, l, t, r, b] = d;
    const struck = id === scene.struck;
    const onset = scene.onsets[id];
    const hazard = onset != null && now >= onset;
    let colour = hazard ? AMBER : struck ? STRUCK : FAINT;
    let width = struck ? 2 : 1;
    if (struck && atImpact) {
      colour = IMPACT;
      width = 4;
    }
    ctx.lineWidth = width;
    ctx.strokeStyle = colour;
    ctx.strokeRect(l * sx, t * sy, (r - l) * sx, (b - t) * sy);
    if (struck || hazard) {
      const label = struck ? (atImpact ? 'Struck vehicle: impact' : 'Struck vehicle') : 'Hazard';
      ctx.font = VEHICLE_FONT;
      const w = ctx.measureText(label).width + 10;
      const x = Math.max(0, Math.min(l * sx, canvas.width - w));
      const y = Math.max(t * sy - 6, 14);
      ctx.fillStyle = 'rgba(0,0,0,0.6)';
      ctx.fillRect(x, y - 13, w, 17);
      ctx.fillStyle = colour;
      ctx.fillText(label, x + 5, y);
    }
  }
}
