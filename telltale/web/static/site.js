/* "Upload your own clip". The hosted site never uploads: the button opens a short note on running it locally.
   When `telltale upload-ui` serves these pages it marks them, and the same button opens the local upload page. */
(() => {
  const button = document.getElementById('upload-own');
  const panel = document.getElementById('upload-panel');
  if (!button || !panel) return;
  const local = document.querySelector('meta[name="upload"][content="local"]');
  const show = (open) => {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
  };
  button.onclick = () => {
    if (local) {
      location.href = '/';
      return;
    }
    show(panel.hidden);
  };
  document.getElementById('upload-close').onclick = () => show(false);
})();
