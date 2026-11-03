"""Native batch-hook controls on recorded ridge and association trials."""
from copy import deepcopy
import json
import os
from pathlib import Path

import numpy as np
import pytest

from dopplergeist import batch_ridge, geometry, matching, search
from dopplergeist.data_access import FlightIndex

trial_prefix = pytest.importorskip("dopplergeist.trial_prefix")
ROOT = Path(trial_prefix.__file__).resolve().parents[2]


@pytest.fixture
def recorded_batch():
    if getattr(matching, "_native_fit_irls_batch", None) is None:
        pytest.skip("optional native batch fitter is unavailable")
    data = json.loads((ROOT / "tests/data/real-ridge-batch-arithmetic.json").read_text())
    measurement = (matching.RidgeTimes(np.asarray(data["times"], dtype=float)),
                   np.asarray(data["ridge"], dtype=float), np.asarray(data["weight"], dtype=float), {})
    return measurement, deepcopy(data["event"]), np.asarray(data["factors"]), np.asarray(data["emissions"])


def identity(value):
    def scalar(item):
        return vars(item) if isinstance(item, geometry.AcousticSupportError) else item.tolist()
    return json.dumps(value, sort_keys=True, allow_nan=True, default=scalar)


def test_changed_native_batch_hook_keeps_original_public_inputs(recorded_batch, monkeypatch):
    measurement, event, _, _ = recorded_batch
    original = matching._native_fit_irls_batch

    @matching._cache_ridge_fits
    def run():
        events, measurements = [event], [measurement]
        prepared_events, prepared_measurements = matching._prepare_score_inputs(events, measurements)
        assert prepared_measurements[0] is not measurement
        assert matching._prepared_score_tokens(prepared_measurements, prepared_events) is not None
        monkeypatch.setattr(matching, "_native_fit_irls_batch", lambda *args: original(*args))
        actual_events, actual_measurements = matching._prepare_score_inputs(events, measurements)
        assert actual_events is events
        assert actual_measurements is measurements
        assert matching._prepared_score_tokens(prepared_measurements, prepared_events) is None
    run()


def test_changed_native_batch_hook_cannot_reuse_predecessor_fit_snapshot(recorded_batch, monkeypatch):
    original = matching._native_fit_irls_batch
    calls = []

    def custom(*args):
        calls.append(1)
        success = original(*args)
        if success:
            # Change computed diagnostics through the hook, keeping all recorded
            # ridge and track observations untouched.
            args[-1][:, 0] = np.nextafter(args[-1][:, 0], -np.inf)
        return success

    @matching._cache_ridge_fits
    def run():
        expected_original = batch_ridge.first_event_fits(*recorded_batch)
        assert expected_original is not None
        assert matching._ridge_fit_cache.get().batch_fit_entries
        with monkeypatch.context() as patch:
            patch.setattr(matching, "_native_fit_irls_batch", custom)
            expected = batch_ridge._first_event_fits_uncached(*recorded_batch)
            assert identity(expected) != identity(expected_original)
            calls.clear()
            actual = batch_ridge.first_event_fits(*recorded_batch)
            assert calls, "The previous native batch's cached fit hid the changed hook"
            assert identity(actual) == identity(expected)
            # Reuse within the same hook identity retains the established fit
            # cache contract; switching back must invalidate that snapshot.
            assert identity(batch_ridge.first_event_fits(*recorded_batch)) == identity(expected)
        restored = batch_ridge.first_event_fits(*recorded_batch)
        assert identity(restored) == identity(expected_original)
    run()


@pytest.fixture(scope="module")
def recorded_prefix():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the recorded CPA diagnostic")
    fixture = json.loads(Path(source).read_text())
    witness = json.loads((ROOT / "tests/data/real-trial-prefix.json").read_text())["calls"]
    events, measurements = matching.prepare_events(fixture["events"])
    names = sorted({name for item in witness for name in item["track_ids"]})
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(
        names, max_tracks=2000, max_samples=2000000)}
    assert set(tracks) == set(names)
    return events, measurements, tracks, witness


def test_changed_native_batch_hook_bypasses_previously_eliminated_prefix(
        recorded_batch, recorded_prefix, monkeypatch):
    events, measurements, tracks, witness = recorded_prefix
    original = matching._native_fit_irls_batch
    calls = []

    def custom(*args):
        calls.append(1)
        return original(*args)

    @matching._cache_ridge_fits
    def run():
        prepared_events, prepared_measurements = matching._prepare_score_inputs(events, measurements)
        by_id = {event["event_id"]: (event, measured)
                 for event, measured in zip(prepared_events, prepared_measurements)}
        options = []
        for item in witness:
            selected = [by_id[name] for name in item["event_ids"]]
            options.append(dict(tracks=[tracks[name] for name in item["track_ids"]],
                events=[pair[0] for pair in selected], measurements=[pair[1] for pair in selected],
                observer=np.asarray(item["observer"]), starts=np.asarray(item["starts"]),
                c=item["c"], score_floor=item["score_floor"], use_dual=item["use_dual"],
                legacy_first_batch=item["legacy_first_batch"]))

        def acoustic(call):
            return matching._iter_acoustic_trials(call["tracks"], call["measurements"],
                call["observer"], call["starts"], call["c"])

        def evaluate(call):
            return search._batched_ridge_trials(**call, acoustic_batches=acoustic(call))

        first, second = options
        assert trial_prefix._canonical()
        evaluate(first)
        assert matching._ridge_fit_cache.get().prefix_memo.entries
        before = trial_prefix.cache_stats()["hits"]
        with monkeypatch.context() as patch:
            patch.setattr(matching, "_native_fit_irls_batch", custom)
            assert not trial_prefix._canonical()
            assert trial_prefix.request(**second, acoustic_batches=acoustic(second)) is None
            actual = evaluate(second)
            assert calls, "A cached eliminated prefix or fit snapshot hid the batch hook"
            assert trial_prefix.cache_stats()["hits"] == before
            patch.setattr(trial_prefix, "_MAX_ENTRIES", 0)
            patch.setattr(matching._ridge_fit_cache.get(), "batch_fit_limit", 0)
            expected = evaluate(second)
            assert identity(actual) == identity(expected)
        assert trial_prefix._canonical()
    run()
