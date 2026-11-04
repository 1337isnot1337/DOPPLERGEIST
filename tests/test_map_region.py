"""Search-area input and packaged-map transport checks; no audio or tracks."""
from copy import deepcopy
from http.server import ThreadingHTTPServer
from importlib.resources import files
import threading
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

from dopplergeist.contracts import validate_request
from dopplergeist.service import Handler


def request_for(search):
    return {"schema_version": 1, "audio_path": "recording.mp3", "search": search}


def test_real_regional_bounds_preserve_precision_and_canonical_coverage():
    # Published Rochester experiment bounds; these only validate input geometry.
    original = request_for({"coverage": "conus", "bounds_wsen": [-77.90, 43.08, -77.50, 43.30]})
    before = deepcopy(original)
    assert validate_request(original) == original
    assert original == before
    assert validate_request(request_for({"coverage": "conus"}))["search"] == {"coverage": "conus"}


@pytest.mark.parametrize("coverage", ["custom", "bbox", "global"])
def test_unsupported_coverage_never_defaults_to_national_search(coverage):
    with pytest.raises(ValueError, match="CONUS"):
        validate_request(request_for({"coverage": coverage}))
    with pytest.raises(ValueError, match="CONUS"):
        validate_request(request_for({"coverage": coverage, "bounds_wsen": [-77.90, 43.08, -77.50, 43.30]}))


@pytest.mark.parametrize("bounds", [
    [], [-77.90, 43.08, -77.50], [-77.90, 43.08, None, 43.30],
    [-77.90, 43.08, float("nan"), 43.30], [-77.90, 43.08, float("inf"), 43.30],
    [-77.50, 43.08, -77.90, 43.30], [170, 24, -170, 50],
    [-126, 24, -66, 50], [-125, 23, -66, 50],
    [-125, 24, -65, 50], [-125, 24, -66, 51],
])
def test_invalid_or_unsupported_bounds_are_rejected_without_repair(bounds):
    with pytest.raises(ValueError):
        validate_request(request_for({"coverage": "conus", "bounds_wsen": bounds}))


def test_map_assets_and_license_are_served_with_restricted_script_policy():
    # A static-only server avoids job submission, decoder work and test recordings.
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.manager = SimpleNamespace()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            root = f"http://127.0.0.1:{server.server_port}"
            for name in ("leaflet.js", "leaflet.css", "leaflet-license.txt"):
                with urlopen(f"{root}/{name}", timeout=5) as response:
                    assert response.read() == files("dopplergeist.web").joinpath(name).read_bytes()
                    policy = response.headers["Content-Security-Policy"]
                    assert "script-src 'self';" in policy
                    assert "'unsafe-inline'" not in policy
                    assert "https://tile.openstreetmap.org" in policy
            with urlopen(root, timeout=5) as response:
                html = response.read().decode()
                assert 'href="/leaflet-license.txt"' in html
                assert 'href="https://www.openstreetmap.org/copyright"' in html
        finally:
            server.shutdown()
            worker.join()
