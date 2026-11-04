/* Telltale: the header's "Upload your own clip" button. On the hosted site it explains how to run Telltale
   locally; served by `telltale upload-ui` (UPLOAD_LOCAL, from mode.js), it goes straight to the upload page. */

function initUploadButton() {
  const button = document.getElementById('upload-open');
  const panel = document.getElementById('upload-panel');
  if (!button || !panel) return;
  if (UPLOAD_LOCAL) {
    button.addEventListener('click', () => window.location.assign('/upload'));
    return;
  }
  const close = () => {
    panel.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    button.focus();
  };
  button.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    button.setAttribute('aria-expanded', String(!panel.hidden));
    if (!panel.hidden) panel.querySelector('button').focus();
  });
  panel.querySelector('button').addEventListener('click', close);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !panel.hidden) close();
  });
}

initUploadButton();
