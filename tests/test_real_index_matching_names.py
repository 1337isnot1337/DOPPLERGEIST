"""Check bootstrap membership against the normal query on historical tracks."""
import json
import os
from pathlib import Path

import pytest

from dopplergeist.data_access import FlightIndex


def test_real_index_membership_uses_the_same_query_predicate():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to a real CPA diagnostic")
    fixture = json.loads(Path(source).read_text())
    index = FlightIndex(fixture["real_index"])
    bounds, window = fixture["query_bounds"], fixture["query_time_s"]
    tracks = list(index.query(bounds, window))
    assert tracks
    wanted = {track.id for track in tracks[:25]}
    assert index.matching_names(wanted, bounds, window) == wanted
    before = [window[0] - 172800, window[0] - 86400]
    expected = wanted & {track.id for track in index.query(bounds, before)}
    assert index.matching_names(wanted, bounds, before) == expected

    # Fault-inject an older index that must conservatively disable its R-tree.
    index.report["continuous_geometry_bounds"] = False
    expected = wanted & {track.id for track in index.query(bounds, window)}
    assert index.matching_names(wanted, bounds, window) == expected
