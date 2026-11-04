import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from telltale.pipeline.investigate_clip import STEPS, ClipInputError
from telltale.web.export import export_site
from telltale.web.upload import CONSENT, make_server

BUNDLE = {
    "clip_id": "mine",
    "video_url": "media/mine.mp4",
    "fps": 30.0,
    "width": 1280,
    "height": 720,
    "lane_polygon": [],
    "tracks": {},
    "report": {},
}


@pytest.fixture
def server(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<!doctype html><title>site</title>")
    calls = {"investigate": [], "publish": [], "outcome": None}

    def investigate(path, clip_id, event_time, progress):
        calls["investigate"].append((path, clip_id, event_time))
        for key, _ in STEPS:
            progress(key)
        if calls["outcome"]:
            raise calls["outcome"]
        return {**BUNDLE, "clip_id": clip_id}

    def publish(bundle, out):
        calls["publish"].append((bundle["clip_id"], out))

    srv = make_server(
        0,
        site=site,
        uploads=tmp_path / "uploads",
        investigate=investigate,
        publish=publish,
        existing_clip_ids=lambda: {"cand36"},
        max_bytes=64,
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield {"srv": srv, "calls": calls, "tmp": tmp_path, "base": f"http://127.0.0.1:{srv.server_address[1]}"}
    srv.shutdown()
    srv.server_close()


def fetch(target):
    """Every request here goes to the local test server over http."""
    return urllib.request.urlopen(target)  # noqa: S310 - fixed http://127.0.0.1 URLs built by these tests


def post(base, clip_id="mine", impact_t="7.4", name="dash.mp4", ctype="video/mp4", body=b"\x00" * 16):
    query = urllib.parse.urlencode({"clip_id": clip_id, "impact_t": impact_t})
    req = urllib.request.Request(  # noqa: S310 - fixed http://127.0.0.1 URL built by these tests
        f"{base}/api/upload?{query}", data=body, method="POST", headers={"Content-Type": ctype, "X-Filename": name}
    )
    try:
        with fetch(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def status(base, clip_id="mine"):
    with fetch(f"{base}/api/status?clip_id={clip_id}") as r:
        return json.loads(r.read())


def wait_until_finished(base, clip_id="mine"):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        s = status(base, clip_id)
        if s["state"] != "running":
            return s
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_server_binds_to_localhost_only(server):
    assert server["srv"].server_address[0] == "127.0.0.1"


def test_valid_upload_runs_the_job_to_done(server):
    code, body = post(server["base"])
    assert (code, body) == (202, {"clip_id": "mine", "state": "running"})
    done = wait_until_finished(server["base"])
    assert done["state"] == "done"
    assert done["link"] == "clips.html?clip=mine"
    assert [s["label"] for s in done["steps"]] == [label for _, label in STEPS]
    assert all(s["state"] == "done" for s in done["steps"])
    saved = server["tmp"] / "uploads" / "mine.mp4"
    assert saved.read_bytes() == b"\x00" * 16
    assert server["calls"]["investigate"] == [(saved, "mine", 7.4)]
    assert server["calls"]["publish"] == [("mine", server["tmp"] / "site")]


def test_server_chooses_the_path_whatever_the_client_names_the_file(server):
    post(server["base"], name="../../etc/passwd.mp4")
    wait_until_finished(server["base"])
    assert [p.name for p in (server["tmp"] / "uploads").iterdir()] == ["mine.mp4"]


@pytest.mark.parametrize(
    ("kwargs", "code", "message"),
    [
        ({"clip_id": "../evil"}, 400, "letters, digits, hyphens and underscores"),
        ({"clip_id": "cand36"}, 409, "already used"),
        ({"impact_t": "soon"}, 400, "Impact time must be a number"),
        ({"impact_t": "nan"}, 400, "Impact time must be a number"),
        ({"name": "dash.avi", "ctype": "video/x-msvideo"}, 415, "Upload an .mp4 or .mov file"),
        ({"name": "dash.mp4", "ctype": "text/plain"}, 415, "Upload an .mp4 or .mov file"),
        ({"body": b"\x00" * 65}, 413, "the limit is"),
    ],
)
def test_bad_uploads_are_rejected_with_a_clear_message(server, kwargs, code, message):
    got_code, body = post(server["base"], **kwargs)
    assert got_code == code
    assert message in body["error"]
    assert server["calls"]["investigate"] == []
    assert not (server["tmp"] / "uploads").exists() or not any((server["tmp"] / "uploads").iterdir())


def test_a_fixable_input_error_in_the_job_is_shown_as_is(server):
    server["calls"]["outcome"] = ClipInputError("Impact time 99.00 s is outside the clip, which is 9.47 s long.")
    post(server["base"])
    done = wait_until_finished(server["base"])
    assert done["state"] == "error"
    assert done["message"] == "Impact time 99.00 s is outside the clip, which is 9.47 s long."


def test_an_unexpected_failure_never_reaches_the_page_as_a_trace(server):
    server["calls"]["outcome"] = RuntimeError("Traceback ... sk-secret-123 at /Users/someone")
    post(server["base"])
    done = wait_until_finished(server["base"])
    assert done["state"] == "error"
    assert "sk-secret" not in done["message"]
    assert "Traceback" not in done["message"]
    assert "terminal running telltale upload-ui" in done["message"]


def test_status_of_an_unknown_clip_is_a_clear_404(server):
    with pytest.raises(urllib.error.HTTPError) as err:
        status(server["base"], "nothing")
    assert err.value.code == 404


def test_upload_page_states_the_consent_before_upload_and_sends_a_csp(server):
    with fetch(f"{server['base']}/") as r:
        page = r.read().decode()
        csp = r.headers["Content-Security-Policy"]
    assert CONSENT in page
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp


def test_the_built_site_is_served_alongside(server):
    with fetch(f"{server['base']}/index.html") as r:
        assert b"<title>site</title>" in r.read()


def test_exported_static_site_has_no_upload_page_or_route(tmp_path):
    site = export_site(
        tmp_path / "none", tmp_path / "site", clips_dir=tmp_path, thumbs_dir=tmp_path, video_bundles_dir=tmp_path / "v"
    )
    names = {p.name for p in site.rglob("*")}
    assert not {"upload.html", "upload.js"} & names
    for path in site.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".js", ".json"}:
            assert "/api/upload" not in path.read_text(), path.name
