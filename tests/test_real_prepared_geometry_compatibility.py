"""Prepared-index compatibility across exact recorded-source revisions."""
import json
import os
from pathlib import Path
import sqlite3

import pytest

from dopplergeist import data_access, index_compatibility
from test_real_prepared_index import observed_index, queried, signature


@pytest.mark.parametrize("previous_geometry", [
    pytest.param("aff5eb70f00766a1a3ab890d1ba33f1a4989af9cf1c4b628770a8d2a7767fd13",
                 id="before-finite-distance-guard"),
    pytest.param("85336bd0e3739f890386e9f93965cefb78c4477ae2e8a4fe489353501c5e26a2",
                 id="before-interval-proof"),
])
@pytest.mark.parametrize("legacy_access", [False, True], ids=["current-access", "legacy-access"])
def test_pinned_legacy_geometry_and_data_source_preserve_real_tracks(
        observed_index, monkeypatch, previous_geometry, legacy_access):
    index, coverage = observed_index
    expected = [signature(track) for track in queried(index, coverage)]
    access = data_access.sha256(Path(data_access.__file__))
    geometry = data_access.sha256(Path(data_access.__file__).with_name("geometry.py"))
    previous_access = index_compatibility.PREPARED_DATA_ACCESS_EQUIVALENCE[access][0] if legacy_access else access
    assert previous_geometry in index_compatibility.PREPARED_GEOMETRY_EQUIVALENCE[geometry]
    # Relabel only the builder metadata in this disposable index. The aircraft
    # observations and prepared bytes are unchanged recorded observations.
    with sqlite3.connect(index.path) as db:
        report = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        report["prepared_tracks"]["builder"] = data_access._prepared_track_identity(previous_access, previous_geometry)
        db.execute("UPDATE metadata SET value=?", (json.dumps(report),))
    reused = data_access.FlightIndex(index.path, track_cache_bytes=0)
    assert reused._prepared_tracks
    assert [signature(track) for track in queried(reused, coverage)] == expected
    with monkeypatch.context() as patch:
        patch.setattr(index_compatibility, "PREPARED_GEOMETRY_EQUIVALENCE", {})
        assert not data_access.FlightIndex(index.path)._prepared_tracks
    with monkeypatch.context() as patch:
        patch.setattr(index_compatibility, "PREPARED_DATA_ACCESS_EQUIVALENCE", {})
        assert data_access.FlightIndex(index.path)._prepared_tracks is (not legacy_access)
    with monkeypatch.context() as patch:
        patch.setattr(data_access, "_prepared_track_identity", lambda *args: "different-runtime")
        assert not data_access.FlightIndex(index.path)._prepared_tracks
    original_sha256 = data_access.sha256
    for modified_name in ("data_access.py", "geometry.py"):
        with monkeypatch.context() as patch:
            patch.setattr(data_access, "sha256", lambda path: "0" * 64 if Path(path).name == modified_name
                          else original_sha256(path))
            assert not data_access.FlightIndex(index.path)._prepared_tracks


@pytest.mark.parametrize("version", ["7f52ff0-parent", "54bc027", "470b708", "ee23896", "4cbdec8", "0071db4"])
def test_actual_prior_prepared_indexes_match_verified_raw_tracks(version, monkeypatch):
    root = os.environ.get("DOPPLERGEIST_REAL_GEOMETRY_PREPARED_DIR")
    if not root:
        pytest.skip("set the directory containing prepared copies from the pinned real source versions")
    index = data_access.FlightIndex(Path(root) / f"{version}.sqlite", track_cache_bytes=0)
    assert index._prepared_tracks
    scope = index.report["prepared_tracks"]["scope"]
    raw = data_access.FlightIndex(index.path, track_cache_bytes=0)
    raw._prepared_tracks = False
    expected = list(raw.query(scope["bounds"], scope["time_range_s"]))
    actual = list(index.query(scope["bounds"], scope["time_range_s"]))
    assert expected
    assert [signature(track) for track in actual] == [signature(track) for track in expected]
    if version != "0071db4":
        with monkeypatch.context() as patch:
            patch.setattr(index_compatibility, "PREPARED_GEOMETRY_EQUIVALENCE", {})
            assert not data_access.FlightIndex(index.path)._prepared_tracks
