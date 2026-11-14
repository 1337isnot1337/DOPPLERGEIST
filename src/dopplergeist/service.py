"""Local upload/job API, sharing the automatic CLI's persistent job manager."""
import base64
import hmac
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .event_reviews import apply_review, read_reviews
from .geography import public_profiles
from .jobs import JobManager, TERMINAL

_EXCLUDED_ARTIFACTS = {"operator.json", "cancel", ".control.lock"}
_SENSITIVE_LOCATION_OUTPUTS = {"search", "refined-candidates.json", "decision.json", "spectral-comparison.json"}
_RESTRICTED_RESULT_CODES = {"restricted_location", "region_policy_unavailable"}
_INLINE_SUFFIXES = {".png", ".svg", ".wav", ".mp3", ".flac", ".m4a", ".ogg"}
_JSON_BODY_LIMIT = 64 * 1024


def hosted_settings():
    """Require a complete hosted configuration before opening the listener."""
    origin = os.environ.get("DOPPLERGEIST_PUBLIC_ORIGIN")
    username = os.environ.get("DOPPLERGEIST_AUTH_USER")
    password = os.environ.get("DOPPLERGEIST_AUTH_PASSWORD")
    if origin is None and username is None and password is None:
        return None, None
    if not origin or not password or not password.strip():
        raise ValueError("Hosted mode requires DOPPLERGEIST_PUBLIC_ORIGIN and DOPPLERGEIST_AUTH_PASSWORD")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or origin != "https://" + parsed.netloc
            or any(c.isspace() or ord(c) < 32 or c == "\\" for c in origin)):
        raise ValueError("DOPPLERGEIST_PUBLIC_ORIGIN must be an HTTPS origin without a path or credentials")
    # Accessing port validates malformed/non-numeric/out-of-range ports too.
    if parsed.port == 0:
        raise ValueError("DOPPLERGEIST_PUBLIC_ORIGIN has an invalid port")
    username = "dopplergeist" if username is None else username
    if not username.strip() or ":" in username or any(ord(c) < 32 for c in username + password):
        raise ValueError("Hosted credentials require a nonempty username without a colon or control characters")
    credentials = base64.b64encode(f"{username}:{password}".encode("utf-8"))
    return origin, credentials


class JobServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, manager):
        if address[0] not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            raise ValueError("Bind host must be 127.0.0.1, localhost or 0.0.0.0")
        self.public_origin, self.credentials = hosted_settings()
        self.manager = manager
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _reply(self, value, code=200, *, headers=None):
        body = json.dumps(value, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _check_origin(self):
        if self.server.public_origin:
            allowed = {urlsplit(self.server.public_origin).netloc}
            origins = {self.server.public_origin}
        else:
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origins = {"http://" + host for host in allowed}
        if len(self.headers.get_all("Host", [])) != 1 or self.headers.get("Host") not in allowed:
            raise PermissionError("Invalid Host header")
        origin = self.headers.get("Origin")
        if (len(self.headers.get_all("Origin", [])) > 1 or (origin and origin not in origins)
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            raise PermissionError("Requests must originate from this interface")

    def _authenticate(self):
        if self.server.credentials is None:
            return True
        authorization = self.headers.get_all("Authorization", [])
        if len(authorization) == 1:
            scheme, _, token = authorization[0].partition(" ")
            if scheme.lower() == "basic" and hmac.compare_digest(token.encode("utf-8"), self.server.credentials):
                return True
        self.close_connection = True
        self._reply({"error": "Authentication required"}, 401,
                    headers={"WWW-Authenticate": 'Basic realm="DOPPLERGEIST", charset="UTF-8"'})
        return False

    def _json_body(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Send review data as application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid Content-Length") from None
        if length <= 0 or length > _JSON_BODY_LIMIT:
            raise ValueError(f"Review body must contain 1..{_JSON_BODY_LIMIT} bytes")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid review JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("Review body must be a JSON object")
        return value

    def _route(self):
        if not self._authenticate():
            return
        self._check_origin()
        parts = [unquote(p) for p in urlsplit(self.path).path.strip("/").split("/")]
        manager = self.server.manager
        if self.command == "GET" and parts == ["api", "capabilities"]:
            return self._reply({"schema_version": 1, "coverage": "conus", "max_upload_bytes": manager.max_upload_bytes,
                                "default_country": "US", "countries": public_profiles(),
                                "max_runtime_s": manager.max_runtime_s, "max_pending": manager.max_pending,
                                "provider_configured": bool(manager.config.get("cache_root") or manager.config.get("flight_indexes")),
                                "online_enabled": not bool(manager.config.get("offline", True))})
        if self.command == "POST" and parts == ["api", "jobs"]:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Use a Content-Length upload")
            if self.headers.get_content_type() != "application/octet-stream":
                raise ValueError("Upload raw audio as application/octet-stream")
            metadata = json.loads(self.headers.get("X-Dopplergeist-Request", "{}"))
            if not isinstance(metadata, dict) or "audio_path" in metadata:
                raise ValueError("Upload metadata must be a request object without audio_path")
            size = int(self.headers.get("Content-Length", "0"))
            suffix = Path(self.headers.get("X-Filename", "input.mp3")).suffix
            self.connection.settimeout(30)
            return self._reply(manager.submit(metadata, self.rfile, size, suffix=suffix), 202)
        if len(parts) >= 3 and parts[:2] == ["api", "jobs"]:
            job_id = parts[2]
            if self.command == "GET" and len(parts) == 3:
                from .jobs import status_for_display
                directory = manager.directory(job_id)
                return self._reply(status_for_display(directory, manager.get(job_id)))
            if self.command == "GET" and parts[3:] == ["reviews"]:
                return self._reply(read_reviews(manager.directory(job_id)))
            if self.command == "POST" and parts[3:] == ["reviews"]:
                current = manager.get(job_id)
                known = [event["event_id"] for event in current.get("events", [])]
                if not known:
                    raise ValueError("This job has no discovered events to review")
                body = self._json_body()
                if body.keys() - {"label", "event_ids", "note"}:
                    raise ValueError("Review body accepts only label, event_ids and note")
                return self._reply(apply_review(manager.directory(job_id), known,
                                                body.get("label"), body.get("event_ids"),
                                                body.get("note")))
            if self.command == "POST" and parts[3:] == ["reanalyze"]:
                return self._reply(manager.reanalyze(job_id), 202)
            if self.command == "GET" and parts[3:] == ["guidance"]:
                from .guidance import explain_job
                return self._reply(explain_job(manager.directory(job_id)))
            if self.command == "POST" and parts[3:] == ["cancel"]:
                return self._reply(manager.cancel(job_id))
            if self.command == "POST" and parts[3:] == ["resume"]:
                return self._reply(manager.resume(job_id), 202)
            if self.command == "GET" and parts[3:] == ["artifacts"]:
                current = manager.get(job_id)
                if current.get("reason_code") in _RESTRICTED_RESULT_CODES:
                    raise PermissionError("Location artifacts are unavailable for this result.")
                directory = manager.directory(job_id)
                artifacts = []
                for path in sorted(directory.rglob("*")):
                    relative = path.relative_to(directory)
                    if (path.is_file() and not path.is_symlink() and path.name not in _EXCLUDED_ARTIFACTS
                            and not path.name.endswith(".tmp")
                            and (current.get("status") in TERMINAL
                                 or relative.parts[0] not in _SENSITIVE_LOCATION_OUTPUTS)):
                        artifacts.append({"path": relative.as_posix(), "bytes": path.stat().st_size})
                return self._reply({"artifacts": artifacts})
            if self.command == "GET" and len(parts) > 4 and parts[3] == "artifacts":
                current = manager.get(job_id)
                if current.get("reason_code") in _RESTRICTED_RESULT_CODES:
                    raise PermissionError("Location artifacts are unavailable for this result.")
                directory = manager.directory(job_id)
                relative = Path(*parts[4:])
                path = (directory / relative).resolve()
                if (path == directory or directory not in path.parents or not path.is_file()
                        or any(part in _EXCLUDED_ARTIFACTS for part in relative.parts)
                        or relative.name.endswith(".tmp")):
                    raise KeyError("Unknown artifact")
                resolved_relative = path.relative_to(directory)
                if (current.get("status") not in TERMINAL
                        and resolved_relative.parts[0] in _SENSITIVE_LOCATION_OUTPUTS):
                    raise PermissionError("Location artifacts are unavailable while analysis is running.")
                return self._file(path, download=path.suffix.lower() not in _INLINE_SUFFIXES)
        if self.command == "GET":
            asset = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css",
                     "/leaflet.js": "leaflet.js", "/leaflet.css": "leaflet.css",
                     "/leaflet-license.txt": "leaflet-license.txt"}.get(urlsplit(self.path).path)
            if asset:
                return self._file(files("dopplergeist.web").joinpath(asset))
        raise KeyError("Unknown endpoint")

    def _file(self, path, download=False):
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name.replace(chr(34), "")}"')
        self.end_headers()
        with path.open("rb") as source:
            while block := source.read(1024*1024):
                self.wfile.write(block)

    def _handle(self):
        try:
            self._route()
        except PermissionError as exc:
            self._reply({"error": str(exc)}, 403)
        except KeyError as exc:
            self._reply({"error": str(exc)}, 404)
        except OverflowError as exc:
            self._reply({"error": str(exc)}, 429)
        except (ValueError, TimeoutError) as exc:
            self._reply({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = _handle
    do_POST = _handle


def serve(root, config=None, *, host="127.0.0.1", port=8765, max_runtime_s=3600, max_upload_bytes=100*1024*1024):
    hosted_settings()
    manager = JobManager(root, config, max_runtime_s=max_runtime_s, max_upload_bytes=max_upload_bytes)
    try:
        with JobServer((host, port), manager) as server:
            print(f"DOPPLERGEIST: http://127.0.0.1:{server.server_port} (bind: {host}; jobs: {manager.root})", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        manager.close()
