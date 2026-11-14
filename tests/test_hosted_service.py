"""Real HTTP transport checks; no audio, tracks, jobs or model outputs generated."""
import base64
from contextlib import contextmanager
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import threading

import pytest

from dopplergeist.jobs import JobManager
from dopplergeist.service import JobServer, serve


ORIGIN = "https://dopplergeist.example"
AUTH = "Basic " + base64.b64encode(b"operator:transport-check-password").decode()
ENVIRONMENT = ("DOPPLERGEIST_PUBLIC_ORIGIN", "DOPPLERGEIST_AUTH_USER", "DOPPLERGEIST_AUTH_PASSWORD")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def hosted_environment(monkeypatch):
    for name, value in zip(ENVIRONMENT, (ORIGIN, "operator", "transport-check-password")):
        monkeypatch.setenv(name, value)


@contextmanager
def running_server(tmp_path):
    manager = JobManager(tmp_path)
    try:
        with JobServer(("127.0.0.1", 0), manager) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield server, manager
            finally:
                server.shutdown()
                thread.join()
    finally:
        manager.close()


def request(server, path="/api/capabilities", *, method="GET", headers=()):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.putrequest(method, path, skip_host=True)
        for name, value in headers:
            connection.putheader(name, value)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.mark.parametrize("path,method", [
    ("/", "GET"), ("/app.js", "GET"), ("/style.css", "GET"),
    ("/api/capabilities", "GET"), ("/api/jobs", "POST"),
    ("/api/jobs/unknown", "GET"), ("/api/jobs/unknown/artifacts", "GET"),
    ("/api/jobs/unknown/artifacts/input.mp3", "GET"),
    ("/api/jobs/unknown/reviews", "POST"), ("/api/jobs/unknown/cancel", "POST"),
    ("/api/jobs/unknown/resume", "POST"), ("/api/jobs/unknown/reanalyze", "POST"),
])
def test_every_route_requires_authentication(tmp_path, monkeypatch, path, method):
    hosted_environment(monkeypatch)
    with running_server(tmp_path) as (server, manager):
        for authorization in (None, "Basic wrong", "Bearer ignored"):
            headers = [("Host", "dopplergeist.example")]
            if authorization:
                headers.append(("Authorization", authorization))
            status, response_headers, body = request(server, path, method=method, headers=headers)
            assert status == 401
            assert response_headers["WWW-Authenticate"].startswith("Basic ")
            assert response_headers["Cache-Control"] == "no-store"
            assert json.loads(body) == {"error": "Authentication required"}
        assert not list(manager.root.glob("*/request.json"))


def test_authenticated_assets_api_and_upload_validation(tmp_path, monkeypatch):
    hosted_environment(monkeypatch)
    headers = [("Host", "dopplergeist.example"), ("Authorization", AUTH), ("Origin", ORIGIN)]
    with running_server(tmp_path) as (server, manager):
        for path in ("/", "/app.js", "/style.css", "/api/capabilities"):
            status, response_headers, body = request(server, path, headers=headers)
            assert status == 200 and body
            assert response_headers["Cache-Control"] == "no-store"
        assert request(server, headers=headers[:2])[0] == 200  # Non-browser clients.
        # Authentication reaches actual upload validation without an audio payload.
        status, _, body = request(server, "/api/jobs", method="POST", headers=headers)
        assert status == 400 and b"application/octet-stream" in body
        assert not list(manager.root.glob("*/request.json"))


@pytest.mark.parametrize("extra", [
    [("Host", "unrelated.example")],
    [("Host", "127.0.0.1:8765")],
    [("Origin", "https://unrelated.example")],
    [("Origin", "http://dopplergeist.example")],
    [("Origin", "null")],
    [("Sec-Fetch-Site", "cross-site")],
    [("Host", "dopplergeist.example"), ("Host", "unrelated.example")],
    [("Origin", ORIGIN), ("Origin", "https://unrelated.example")],
])
def test_authenticated_requests_still_enforce_host_and_origin(tmp_path, monkeypatch, extra):
    hosted_environment(monkeypatch)
    headers = [("Authorization", AUTH)]
    if not any(name == "Host" for name, _ in extra):
        headers.append(("Host", "dopplergeist.example"))
    with running_server(tmp_path) as (server, _):
        assert request(server, headers=headers + extra)[0] == 403


def test_duplicate_authorization_is_rejected(tmp_path, monkeypatch):
    hosted_environment(monkeypatch)
    with running_server(tmp_path) as (server, _):
        assert request(server, headers=[("Host", "dopplergeist.example"),
                                       ("Authorization", AUTH), ("Authorization", AUTH)])[0] == 401


def test_saved_real_artifact_is_protected_and_preserved(tmp_path, monkeypatch):
    hosted_environment(monkeypatch)
    # Reuse a published real-recording summary solely as an opaque download.
    source = Path(__file__).resolve().parents[1] / "evidence/e2e-worker-20261103/real-result-summary.json"
    saved = json.loads(source.read_text())
    directory = tmp_path / saved["job_id"]
    directory.mkdir()
    shutil.copyfile(source, directory / "result.json")
    before = source.read_bytes()
    path = f"/api/jobs/{directory.name}/artifacts/result.json"
    with running_server(tmp_path) as (server, _):
        headers = [("Host", "dopplergeist.example")]
        assert request(server, path, headers=headers)[0] == 401
        status, _, body = request(server, path, headers=headers + [("Authorization", AUTH)])
        assert status == 200 and body == before
    assert (directory / "result.json").read_bytes() == before


@pytest.mark.parametrize("settings", [
    {"DOPPLERGEIST_AUTH_PASSWORD": None, "DOPPLERGEIST_AUTH_USER": None},
    {"DOPPLERGEIST_PUBLIC_ORIGIN": None, "DOPPLERGEIST_AUTH_USER": None},
    {"DOPPLERGEIST_PUBLIC_ORIGIN": None, "DOPPLERGEIST_AUTH_PASSWORD": None},
    {"DOPPLERGEIST_PUBLIC_ORIGIN": ""},
    {"DOPPLERGEIST_AUTH_PASSWORD": ""},
    {"DOPPLERGEIST_AUTH_PASSWORD": "   "},
    {"DOPPLERGEIST_AUTH_USER": ""},
    {"DOPPLERGEIST_AUTH_USER": "user:name"},
    {"DOPPLERGEIST_AUTH_PASSWORD": "password\n"},
    *[{"DOPPLERGEIST_PUBLIC_ORIGIN": origin} for origin in (
        "http://dopplergeist.example", "https://dopplergeist.example/",
        "https://dopplergeist.example/path", "https://user:pass@dopplergeist.example",
        "https://dopplergeist.example?query", "https://dopplergeist.example#fragment",
        "https://dopplergeist.example:wrong", "https://dopplergeist.example:0",
        "https://dopplergeist.example:65536", "https://dopplergeist.example\n",
    )],
])
def test_invalid_hosted_settings_fail_before_listening(tmp_path, monkeypatch, settings):
    hosted_environment(monkeypatch)
    for name, value in settings.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    manager = JobManager(tmp_path)
    try:
        with pytest.raises(ValueError):
            JobServer(("127.0.0.1", 0), manager)
    finally:
        manager.close()


def test_local_defaults_and_host_checks_are_preserved(tmp_path):
    with running_server(tmp_path) as (server, _):
        headers = [("Host", f"127.0.0.1:{server.server_port}")]
        assert request(server, headers=headers)[0] == 200
        assert request(server, headers=[("Host", "dopplergeist.example")])[0] == 403
        assert request(server, headers=headers + [("Origin", "https://unrelated.example")])[0] == 403


def test_invalid_settings_do_not_open_or_recover_the_job_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DOPPLERGEIST_PUBLIC_ORIGIN", ORIGIN)
    root = tmp_path / "jobs"
    with pytest.raises(ValueError):
        serve(root, port=0)
    assert not root.exists()


def test_default_username_and_https_port(tmp_path, monkeypatch):
    hosted_environment(monkeypatch)
    monkeypatch.delenv("DOPPLERGEIST_AUTH_USER")
    monkeypatch.setenv("DOPPLERGEIST_PUBLIC_ORIGIN", "https://dopplergeist.example:8443")
    authorization = "basic " + base64.b64encode(b"dopplergeist:transport-check-password").decode()
    with running_server(tmp_path) as (server, _):
        headers = [("Host", "dopplergeist.example:8443"), ("Authorization", authorization),
                   ("Origin", "https://dopplergeist.example:8443")]
        assert request(server, headers=headers)[0] == 200
