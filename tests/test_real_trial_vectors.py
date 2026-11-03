"""Clock-vector screens preserve scalar decisions on recorded associations."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist import acoustic_screen, batch_ridge, matching, search
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import AcousticSupportError, ecef


@pytest.fixture(scope="module")
def recorded_associations():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to an actual recorded-data diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = matching.prepare_events(fixture["events"])
    candidates, _ = matching.association_candidates(
        pd.DataFrame(fixture["cpa_rows"]), events,
        max_candidates=fixture.get("budget", {}).get("max_candidates_per_tile", 20000),
        anchor_window=fixture.get("recording_start_window_s"))
    grouped = {}
    for candidate in candidates:
        count = len(candidate["event_indices"])
        if count >= 2:
            grouped.setdefault(count, []).append(candidate)
    assert grouped, "Recorded fixture needs a multiple-group association"
    sizes = sorted(grouped)
    selected = [grouped[size][position]
                for size in sorted({sizes[0], sizes[len(sizes) // 2], sizes[-1]})
                for position in (0, -1)]
    identifiers = sorted({entry["flight_id"] for candidate in selected for entry in candidate["passes"]})
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(identifiers)}
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    result = []
    for candidate in selected:
        indices = candidate["event_indices"]
        chosen_tracks = [tracks[entry["flight_id"]] for entry in candidate["passes"]]
        chosen_events = [events[index] for index in indices]
        chosen_measurements = [measurements[index] for index in indices]
        lower, upper = candidate["recording_start_bounds_s"]
        starts = np.linspace(lower - 5.0, upper + 5.0, 21)
        batches = matching.batch_acoustic_trials(chosen_tracks, chosen_measurements, observer, starts)
        result.append((chosen_tracks, chosen_events, chosen_measurements, observer, starts, batches))
    return result


def scalar_trials(case, floor, use_dual):
    tracks, events, measurements, observer, starts, batches = case
    flags = [None if batch is None or not use_dual else
             acoustic_screen.ridge_trial_rejections(measurement, event, *batch,
                 score_floor=floor, group_count=len(events))
             for measurement, event, batch in zip(measurements, events, batches)]
    rejected_count = floor_count = 0
    outcomes = []
    for trial, start in enumerate(starts):
        def acoustic_at(index):
            batch = batches[index]
            return None if batch is None else (batch[0][trial], batch[1][trial])

        def dual_at(index):
            nonlocal rejected_count, floor_count
            if flags[index] is None:
                return None
            rejected, upper = flags[index]
            if rejected[trial]:
                rejected_count += 1
                return -np.inf
            if np.isfinite(upper[trial]):
                floor_count += 1
                return float(upper[trial])
            return None

        try:
            result, upper = search._screen_association_trial(
                tracks, events, measurements, observer, start, 343.0,
                acoustic_at, floor, dual_at if use_dual else None)
            outcomes.append((result, upper, None))
        except AcousticSupportError as error:
            outcomes.append((None, None, error))
    return outcomes, rejected_count, floor_count


def encoded(value):
    def default(item):
        if isinstance(item, AcousticSupportError):
            return {"error": str(item), "evidence": vars(item)}
        if isinstance(item, np.ndarray):
            return item.tolist()
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(type(item).__name__)
    return json.dumps(value, sort_keys=True, default=default)


@pytest.mark.parametrize("use_dual", [False, True])
def test_recorded_vectors_keep_scalar_decisions_at_adjacent_float_floors(
        recorded_associations, monkeypatch, use_dual):
    original = batch_ridge._first_event_fits_with_ceilings
    vector_batches = []
    boundary_cases = []

    def counted(*args, **kwargs):
        result = original(*args, **kwargs)
        if result[1] is not None:
            vector_batches.append(1)
        return result

    monkeypatch.setattr(batch_ridge, "_first_event_fits_with_ceilings", counted)

    @matching._cache_ridge_fits
    def run():
        for case in recorded_associations:
            tracks, events, measurements, observer, starts, batches = case
            first_bounds = scalar_trials(case, float(len(events)), False)[0]
            finite = sorted(upper for _, upper, _ in first_bounds
                            if upper is not None and np.isfinite(upper))
            # Exercise the shortcut's remaining-group threshold on both sides
            # as well as actual fitted ceilings below. Observations stay fixed.
            remaining = float(len(events) - 1)
            floors = {0.0, float(len(events)), remaining,
                      float(np.nextafter(remaining, -np.inf)),
                      float(np.nextafter(remaining, np.inf))}
            if finite:
                boundary = finite[len(finite) // 2]
                boundary_cases.append(boundary)
                floors.update((float(np.nextafter(boundary, -np.inf)), boundary,
                               float(np.nextafter(boundary, np.inf))))
            for floor in sorted(floors):
                expected = scalar_trials(case, floor, use_dual)
                actual = search._batched_ridge_trials(
                    tracks, events, measurements, observer, starts, 343.0,
                    iter(batches), floor, use_dual)
                assert encoded(actual) == encoded(expected), (len(events), floor, use_dual)
    run()
    assert vector_batches, "Recorded cases must exercise the canonical ceiling vector"
    assert boundary_cases, "Recorded cases must exercise adjacent-float retention boundaries"


def test_recorded_vectors_keep_noncanonical_validation_fallback(recorded_associations, monkeypatch):
    original = search._ridge_trial_classification

    def custom(*args):
        return original(*args)

    monkeypatch.setattr(search, "_ridge_trial_classification", custom)

    @matching._cache_ridge_fits
    def run():
        for case in recorded_associations:
            tracks, events, measurements, observer, starts, batches = case
            expected = scalar_trials(case, 0.0, False)
            actual = search._batched_ridge_trials(
                tracks, events, measurements, observer, starts, 343.0,
                iter(batches), 0.0, False)
            assert encoded(actual) == encoded(expected)
    run()
