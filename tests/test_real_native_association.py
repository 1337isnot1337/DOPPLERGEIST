"""Native traversal parity on supplied recorded CPA rows; never generate data."""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from dopplergeist import matching


@pytest.fixture(scope="module")
def observed():
    path = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not path:
        pytest.skip("Supply a recorded CPA fixture")
    if matching._native_association is None:
        pytest.skip("Optional native association extension is unavailable")
    fixture = json.loads(Path(path).read_text())
    events, _ = matching.prepare_events(fixture["events"])
    settings = {}
    window = fixture.get("recording_start_window_s")
    if window is not None:
        settings = {"time_origin": sum(window)/2, "time_tolerance_s": (window[1]-window[0])/2}
    return pd.DataFrame(fixture["cpa_rows"]), events, settings


def result_or_error(function, table, events, settings):
    try:
        return function(table, events, **settings)
    except ValueError as error:
        return str(error)


@pytest.mark.parametrize("settings", [
    {}, {"min_events": 2}, {"min_events": 4}, {"max_events": 1}, {"max_events": 2},
    {"max_candidates": 1}, {"max_candidates": 100}, {"max_candidates": 1000},
])
def test_native_preserves_candidates_order_bounds_and_work(observed, monkeypatch, settings):
    table, events, defaults = observed
    settings = dict(defaults, **settings)
    native = matching._native_association
    monkeypatch.setattr(matching, "_native_association", None)
    expected = result_or_error(matching.association_candidates, table, events, settings)
    monkeypatch.setattr(matching, "_native_association", native)
    actual = result_or_error(matching.association_candidates, table, events, settings)
    assert actual == expected


def test_native_preserves_multi_receiver_accounting(observed, monkeypatch):
    table, events, settings = observed
    points = list(table.point_id.unique())
    if len(points) < 2:
        pytest.skip("Fixture contains only one recorded receiver hypothesis")
    native = matching._native_association
    monkeypatch.setattr(matching, "_native_association", None)
    expected = result_or_error(matching.association_candidates, table, events, settings)
    monkeypatch.setattr(matching, "_native_association", native)
    assert result_or_error(matching.association_candidates, table, events, settings) == expected
