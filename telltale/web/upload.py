"""Local-only upload page: drop in your own dashcam clip and watch investigate-clip run on it.

This is a deliberate exception to "static site, no server code". It runs only on your machine, binds to
127.0.0.1, and is never exported: its page lives outside `static/`, so `telltale export-site` and the hosted
Space never contain it. The API key stays in this process, read by `telltale.config` inside the SAM and witness
steps; it never appears in a response, the page, or an error shown to the browser.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from telltale.pipeline.investigate_clip import (
    STEPS,
    UPLOADS,
    ClipInputError,
    check_clip_id,
    investigate_clip,
    taken_clip_ids,
)
from telltale.video.impact import suggest_impact_time
from telltale.web.export import SITE, publish_video_case

logger = logging.getLogger(__name__)

UI = Path(__file__).parent / "upload_ui"
INCOMING = UPLOADS / "incoming"
MAX_BYTES = 200 * 1024 * 1024
VIDEO_TYPES = {".mp4": {"video/mp4"}, ".mov": {"video/quicktime"}}
CONSENT = (
    "This sends your clip to Meta's API. Use only footage you have the right to share. "
    "Free-tier credits allow Meta to use submitted content."
)
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
)
MISSING_KEY = "MODEL_API_KEY is not set"


class UploadRejected(ValueError):
    """An upload refused before any work starts; `status` is the HTTP code to answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Job:
    clip_id: str
    state: str = "running"
    step: str | None = None
    message: str = ""
    finished: set[str] = field(default_factory=set)

    def view(self) -> dict:
        steps = []
        for key, label in STEPS:
            state = "done" if key in self.finished else "active" if key == self.step else "waiting"
            steps.append({"key": key, "label": label, "state": state})
        view = {"clip_id": self.clip_id, "state": self.state, "steps": steps, "message": self.message}
        if self.state == "done":
            view["link"] = f"clips.html?clip={self.clip_id}"
        return view


def _failure_message(exc: Exception, step: str | None) -> str:
    """Something a person can act on. Fixable input errors pass through; anything else stays in the terminal."""
    if isinstance(exc, ClipInputError):
        return str(exc)
    if isinstance(exc, RuntimeError) and str(exc).startswith(MISSING_KEY):
        return "MODEL_API_KEY is not set. Add it to .env, then restart telltale upload-ui."
    label = dict(STEPS).get(step or "", "The investigation")
    return f"{label} failed. See the terminal running telltale upload-ui for details, then try again."


def check_upload(
    query: dict, filename: str, content_type: str, length: int, existing: set[str], max_bytes: int
) -> tuple[str, float, str]:
    """Validate everything before reading the body. Returns the clip id, impact time and file suffix."""
    clip_id = (query.get("clip_id") or [""])[0]
    try:
        check_clip_id(clip_id)
    except ClipInputError as exc:
        raise UploadRejected(400, str(exc)) from exc
    if clip_id in existing:
        raise UploadRejected(409, f"Clip id {clip_id!r} is already used. Choose another.")
    try:
        impact_t = float((query.get("impact_t") or [""])[0])
    except ValueError:
        impact_t = math.nan
    if not math.isfinite(impact_t):
        raise UploadRejected(400, "Impact time must be a number of seconds from the start of the clip, e.g. 7.4.")
    return clip_id, impact_t, check_file(filename, content_type, length, max_bytes)


def check_file(filename: str, content_type: str, length: int, max_bytes: int) -> str:
    """The checks every video body passes before it is read. Returns the file suffix."""
    suffix = Path(filename).suffix.lower()
    if content_type.split(";")[0].strip().lower() not in VIDEO_TYPES.get(suffix, set()):
        raise UploadRejected(415, "Upload an .mp4 or .mov file.")
    if length <= 0:
        raise UploadRejected(411, "The upload was empty. Choose a video file and try again.")
    if length > max_bytes:
        raise UploadRejected(
            413, f"That file is {length / 1e6:.0f} MB; the limit is {max_bytes / 1e6:.0f} MB. Trim the clip first."
        )
    return suffix


def upload_path(uploads: Path, suffix: str) -> Path:
    """Where to save one upload: a server-generated name inside the uploads folder.

    Nothing from the request becomes part of the path. The clip id is only a label and the manifest key, and the
    extension is one of two constants chosen by comparison, not copied from the file name.
    """
    extension = ".mov" if suffix == ".mov" else ".mp4"
    path = uploads / f"{uuid.uuid4().hex}{extension}"
    if not path.resolve().is_relative_to(uploads.resolve()):
        raise UploadRejected(400, "Could not choose a safe place to save the upload. Try again.")
    return path


def make_server(
    port: int = 8001,
    *,
    site: Path = SITE,
    uploads: Path = INCOMING,
    investigate: Callable = investigate_clip,
    publish: Callable[[dict, Path], None] = lambda bundle, site: publish_video_case(bundle, site, UPLOADS / "clips"),
    existing_clip_ids: Callable[[], set[str]] = taken_clip_ids,
    max_bytes: int = MAX_BYTES,
    suggest: Callable[[Path], float | None] = lambda path: suggest_impact_time(video_path=path),
) -> ThreadingHTTPServer:
    """The local upload server, bound to 127.0.0.1. Serves the upload page, its two endpoints, and the site."""
    jobs: dict[str, Job] = {}
    lock = threading.Lock()

    def run(job: Job, path: Path, impact_t: float) -> None:
        def progress(step: str) -> None:
            with lock:
                if job.step:
                    job.finished.add(job.step)
                job.step = step

        try:
            bundle = investigate(path, job.clip_id, impact_t, progress=progress)
            publish(bundle, site)
        except Exception as exc:  # boundary: log it here, show the page a safe message, keep serving
            logger.exception("investigate-clip failed for %s", job.clip_id)
            with lock:
                job.state, job.message = "error", _failure_message(exc, job.step)
            return
        with lock:
            job.finished.update(key for key, _ in STEPS)
            job.state, job.step = "done", None

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            logger.info("%s %s", self.address_string(), format % args)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _ui(self, name: str, content_type: str) -> None:
            body = (UI / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path in ("/", "/upload"):
                return self._ui("upload.html", "text/html; charset=utf-8")
            if url.path == "/mode.js":
                return self._ui("mode.js", "text/javascript; charset=utf-8")
            if url.path == "/upload.js":
                return self._ui("upload.js", "text/javascript; charset=utf-8")
            if url.path == "/api/status":
                clip_id = (parse_qs(url.query).get("clip_id") or [""])[0]
                with lock:
                    job = jobs.get(clip_id)
                    view = job.view() if job else None
                if view is None:
                    return self._json(404, {"error": f"No upload is running for {clip_id!r}."})
                return self._json(200, view)
            return super().do_GET()

        def _save_body(self, path: Path, length: int) -> None:
            with path.open("wb") as out:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1 << 20))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)

        def _suggest(self) -> None:
            """A suggested impact time from the camera jolt. The file is kept only while it is measured."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
                suffix = check_file(
                    self.headers.get("X-Filename", ""), self.headers.get("Content-Type", ""), length, max_bytes
                )
                uploads.mkdir(parents=True, exist_ok=True)
                path = upload_path(uploads, suffix)
            except UploadRejected as exc:
                self.close_connection = True
                return self._json(exc.status, {"error": str(exc)})
            self._save_body(path, length)
            try:
                value = suggest(path)
            except Exception:  # boundary: no suggestion is not an error; the person types the time instead
                logger.exception("could not suggest an impact time")
                value = None
            finally:
                path.unlink(missing_ok=True)
            return self._json(200, {"suggested_t": None if value is None else round(float(value), 2)})

        def do_POST(self) -> None:
            url = urlparse(self.path)
            if url.path == "/api/suggest":
                return self._suggest()
            if url.path != "/api/upload":
                return self._json(404, {"error": "Not found."})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                clip_id, impact_t, suffix = check_upload(
                    parse_qs(url.query),
                    self.headers.get("X-Filename", ""),
                    self.headers.get("Content-Type", ""),
                    length,
                    existing_clip_ids(),
                    max_bytes,
                )
                uploads.mkdir(parents=True, exist_ok=True)
                path = upload_path(uploads, suffix)
                with lock:
                    if clip_id in jobs and jobs[clip_id].state == "running":
                        raise UploadRejected(409, f"An upload for {clip_id!r} is already running.")
                    job = jobs[clip_id] = Job(clip_id)
            except UploadRejected as exc:
                self.close_connection = True
                return self._json(exc.status, {"error": str(exc)})
            self._save_body(path, length)
            threading.Thread(target=run, args=(job, path, impact_t), daemon=True).start()
            return self._json(202, {"clip_id": clip_id, "state": "running"})

    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(site)))
