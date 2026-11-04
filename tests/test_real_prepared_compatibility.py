"""Optional previous-source prepared-index regression on archived aircraft."""
import os
from pathlib import Path

import pytest

from dopplergeist import data_access, index_compatibility
from test_real_prepared_index import signature


@pytest.mark.parametrize("variable", ["DOPPLERGEIST_REAL_PREPARED_BEFORE_CACHE", "DOPPLERGEIST_REAL_PREPARED_AFTER_CACHE",
                                      "DOPPLERGEIST_REAL_PREPARED_AFTER_COMPAT",
                                      "DOPPLERGEIST_REAL_PREPARED_BEFORE_DIGEST"])
def test_prior_prepared_index_is_reused_only_for_pinned_sources(variable, monkeypatch):
    value = os.environ.get(variable)
    if not value:
        pytest.skip("set real prepared indexes made before and after the cache-size change")
    path = Path(value)
    prepared = data_access.FlightIndex(path, track_cache_bytes=0)
    assert prepared._prepared_tracks
    scope = prepared.report["prepared_tracks"]["scope"]
    raw = data_access.FlightIndex(path, track_cache_bytes=0)
    raw._prepared_tracks = False
    expected = list(raw.query(scope["bounds"], scope["time_range_s"]))
    actual = list(prepared.query(scope["bounds"], scope["time_range_s"]))
    assert expected
    assert [signature(track) for track in actual] == [signature(track) for track in expected]
    with monkeypatch.context() as patch:
        patch.setattr(index_compatibility, "PREPARED_DATA_ACCESS_EQUIVALENCE", {})
        assert not data_access.FlightIndex(path, track_cache_bytes=0)._prepared_tracks
    with monkeypatch.context() as patch:
        patch.setattr(data_access, "_prepared_track_identity", lambda *args: "different-runtime")
        assert not data_access.FlightIndex(path, track_cache_bytes=0)._prepared_tracks
