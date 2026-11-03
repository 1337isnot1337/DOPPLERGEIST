"""Eliminated-prefix reuse on recorded ridge/ADS-B association trials."""
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from dopplergeist import acoustic_screen, batch_ridge, geometry, matching, search, trial_prefix
from dopplergeist.data_access import FlightIndex


@pytest.fixture(scope="module")
def recorded():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the recorded reference CPA diagnostic")
    fixture = json.loads(Path(source).read_text())
    witness = json.loads((Path(__file__).parent / "data/real-trial-prefix.json").read_text())
    events, measurements = matching.prepare_events(fixture["events"])
    names = sorted({name for call in witness["calls"] for name in call["track_ids"]})
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(
        names, max_tracks=2000, max_samples=2000000)}
    assert set(tracks) == set(names)
    return events, measurements, tracks, witness["calls"]


def prepared_calls(recorded):
    events, measurements, tracks, specifications = recorded
    events, measurements = matching._prepare_score_inputs(events, measurements)
    by_id = {event["event_id"]: (event, measurement) for event, measurement in zip(events, measurements)}
    calls = []
    for specification in specifications:
        selected = [by_id[name] for name in specification["event_ids"]]
        calls.append(dict(tracks=[tracks[name] for name in specification["track_ids"]],
            events=[pair[0] for pair in selected], measurements=[pair[1] for pair in selected],
            observer=np.asarray(specification["observer"], dtype=float),
            starts=np.asarray(specification["starts"], dtype=float), c=specification["c"],
            score_floor=specification["score_floor"], use_dual=specification["use_dual"],
            legacy_first_batch=specification["legacy_first_batch"]))
    return calls


def acoustic(call, max_samples=262144):
    return matching._iter_acoustic_trials(call["tracks"], call["measurements"], call["observer"],
                                          call["starts"], call["c"], max_samples=max_samples)


def evaluate(call, batches=None):
    return search._batched_ridge_trials(**call, acoustic_batches=acoustic(call) if batches is None else batches)


def identity(value):
    def scalar(item):
        return vars(item) if isinstance(item, geometry.AcousticSupportError) else item.tolist()
    return json.dumps(value, sort_keys=True, allow_nan=True, default=scalar)


def test_real_eliminated_prefix_reuses_exact_outcomes_for_a_different_suffix(recorded, monkeypatch):
    @matching._cache_ridge_fits
    def run():
        first, second = prepared_calls(recorded)
        with monkeypatch.context() as patch:
            patch.setattr(trial_prefix, "_MAX_ENTRIES", 0)
            expected = [identity(evaluate(call)) for call in (first, second)]
        assert expected[0] == expected[1]
        before = trial_prefix.cache_stats()
        initial = evaluate(first)
        assert identity(initial) == expected[0]
        memo = matching._ridge_fit_cache.get().prefix_memo
        assert len(memo.entries) == 1
        assert memo.size + sys.getsizeof(memo.entries) <= trial_prefix._MAX_BYTES
        key, (value, retained, size) = next(iter(memo.entries.items()))
        assert size == trial_prefix._size(key) + trial_prefix._size(value) + sys.getsizeof(retained) + 256
        initial[0][0] = (None, 12345., None)
        assert identity(evaluate(second)) == expected[1]
        after = trial_prefix.cache_stats()
        assert after["hits"] == before["hits"] + 1
        assert after["saved_event_steps"] == before["saved_event_steps"] + 2
        assert after["saved_trials"] == before["saved_trials"] + len(first["starts"])
        return first

    previous = run()
    assert trial_prefix.cache_stats()["entries"] == 0

    @matching._cache_ridge_fits
    def separate_scope():
        assert trial_prefix.request(**previous, acoustic_batches=acoustic(previous)) is None
    separate_scope()


def test_real_prefix_keeps_finite_unknown_bounds_and_support_exceptions(recorded, monkeypatch):
    @matching._cache_ridge_fits
    def bounded():
        call = prepared_calls(recorded)[0]
        call["score_floor"] = float(len(call["events"])) - .05
        with monkeypatch.context() as patch:
            patch.setattr(trial_prefix, "_MAX_ENTRIES", 0)
            expected = evaluate(call)
        assert all(result is None and error is None for result, upper, error in expected[0])
        assert any(np.isfinite(upper) for result, upper, error in expected[0])
        assert identity(evaluate(call)) == identity(expected)
        before = trial_prefix.cache_stats()["hits"]
        assert identity(evaluate(call)) == identity(expected)
        assert trial_prefix.cache_stats()["hits"] == before + 1
    bounded()

    @matching._cache_ridge_fits
    def unsupported():
        call = prepared_calls(recorded)[0]
        # The recorded aircraft motion cannot support this sound-speed control.
        # Its typed physical-model failures must be produced afresh, not stored.
        call["c"] = 1.0
        first, second = evaluate(call), evaluate(call)
        assert identity(first) == identity(second)
        errors = [(a[2], b[2]) for a, b in zip(first[0], second[0]) if a[2] is not None]
        assert errors and all(a is not b for a, b in errors)
        assert not matching._ridge_fit_cache.get().prefix_memo.entries
    unsupported()


@pytest.mark.parametrize("groups,direction", [(2, 0), (3, -1), (3, 0), (3, 1), (8, -1), (8, 0), (8, 1)])
def test_real_residual_prefix_domain_keeps_outward_boundary_and_final_event(recorded, monkeypatch, groups, direction):
    @matching._cache_ridge_fits
    def run():
        source = prepared_calls(recorded)[0]
        target = dict(source)
        for key in ("tracks", "events", "measurements"):
            target[key] = source[key][:groups]
        floor = float(groups - 2)  # This recorded prefix eliminates all clocks after two groups.
        if direction:
            floor = float(np.nextafter(floor, np.inf if direction > 0 else -np.inf))
        target["score_floor"] = floor
        with monkeypatch.context() as patch:
            patch.setattr(trial_prefix, "_MAX_ENTRIES", 0)
            expected = identity(evaluate(target))
        evaluate(source)
        before = trial_prefix.cache_stats()["residual_hits"]
        assert identity(evaluate(target)) == expected
        eligible = groups > 2 and floor <= groups - 2
        assert trial_prefix.cache_stats()["residual_hits"] == before + eligible
    run()


def test_real_residual_prefix_can_originate_at_a_positive_safe_floor(recorded, monkeypatch):
    @matching._cache_ridge_fits
    def run():
        target = prepared_calls(recorded)[0]
        source = dict(target, score_floor=float(len(target["events"]) - 2))
        with monkeypatch.context() as patch:
            patch.setattr(trial_prefix, "_MAX_ENTRIES", 0)
            expected = identity(evaluate(target))
        assert identity(evaluate(source)) == expected
        before = trial_prefix.cache_stats()["residual_hits"]
        assert identity(evaluate(target)) == expected
        assert trial_prefix.cache_stats()["residual_hits"] == before + 1
    run()


@pytest.mark.parametrize("changed", ["floor", "observer", "clock", "c", "groups", "dual", "legacy", "track"])
def test_real_prefix_keys_preserve_changed_scoring_controls(recorded, monkeypatch, changed):
    @matching._cache_ridge_fits
    def run():
        original = prepared_calls(recorded)[0]
        altered = dict(original)
        if changed in ("floor", "c"):
            key = "score_floor" if changed == "floor" else "c"
            altered[key] = float(np.nextafter(original[key], np.inf))
        elif changed in ("observer", "clock"):
            key = "observer" if changed == "observer" else "starts"
            altered[key] = original[key].copy()
            altered[key][0] = np.nextafter(altered[key][0], np.inf)
        elif changed == "groups":
            for key in ("events", "measurements", "tracks"):
                altered[key] = original[key][:-1]
        elif changed in ("dual", "legacy"):
            key = "use_dual" if changed == "dual" else "legacy_first_batch"
            altered[key] = not original[key]
        else:
            altered["tracks"] = list(original["tracks"])
            altered["tracks"][0] = original["tracks"][1]
        with monkeypatch.context() as patch:
            patch.setattr(trial_prefix, "_MAX_ENTRIES", 0)
            expected = identity(evaluate(altered))
        evaluate(original)
        before = trial_prefix.cache_stats()["hits"]
        assert identity(evaluate(altered)) == expected
        assert trial_prefix.cache_stats()["hits"] == before + (changed in ("floor", "groups"))
    run()


@pytest.mark.parametrize("changed", ["bounds", "weight_shape", "clock_budget", "iterator", "policy"])
def test_real_prefix_bypasses_changed_or_noncanonical_inputs(recorded, monkeypatch, changed):
    @matching._cache_ridge_fits
    def run():
        call = prepared_calls(recorded)[0]
        evaluate(call)
        if changed == "bounds":
            call["events"][0]["f0_range_hz"][0] = float("nan")
        elif changed == "weight_shape":
            call["measurements"][0][2].shape = (1, -1)
        if changed == "clock_budget":
            batches = acoustic(call, max_samples=1)
            request = trial_prefix.request(**call, acoustic_batches=batches)
            assert request is not None and request.lookup() is None
        elif changed == "iterator":
            assert trial_prefix.request(**call, acoustic_batches=iter(())) is None
            batches = acoustic(call)
            next(batches)
            assert trial_prefix.request(**call, acoustic_batches=batches) is None
        elif changed == "policy":
            with np.errstate(under="raise"):
                assert trial_prefix.request(**call, acoustic_batches=acoustic(call)) is None
        else:
            assert trial_prefix.request(**call, acoustic_batches=acoustic(call)) is None
    run()


@pytest.mark.parametrize("owner,name", [(matching, "_fit_ridge_uncached"), (matching, "_iter_acoustic_trials"),
    (geometry.Track, "acoustic"), (batch_ridge, "first_event_fits"),
    (acoustic_screen, "ridge_trial_rejections"), (search, "_association_event_ceiling")])
def test_real_prefix_does_not_hide_custom_numerical_hooks(recorded, monkeypatch, owner, name):
    @matching._cache_ridge_fits
    def run():
        call = prepared_calls(recorded)[0]
        evaluate(call)
        original = getattr(owner, name)
        monkeypatch.setattr(owner, name, lambda *args, **kwargs: original(*args, **kwargs))
        assert trial_prefix.request(**call, acoustic_batches=acoustic(call)) is None
    run()


@pytest.mark.parametrize("module,name", [("acoustic_screen", "_frequency_scale"),
    ("batch_ridge", "_frequency_scale"), ("batch_ridge", "_ridge_fit_inputs"),
    ("batch_ridge", "_fit_ridge_uncached"), ("batch_ridge", "_fit_argument_key"),
    ("search", "_native_validate_ridge_events")])
def test_real_prefix_rejects_custom_aliases_retained_by_module_import(recorded, module, name):
    code = """
import importlib
import json
from pathlib import Path
import sys
import numpy as np
from dopplergeist import matching
module_name, name, source, directory = sys.argv[1:]
original = getattr(matching, name)
calls = 0
def hook(*args, **kwargs):
    global calls
    calls += 1
    return False if original is None else original(*args, **kwargs)
setattr(matching, name, hook)
consumer = importlib.import_module('dopplergeist.' + module_name)
setattr(matching, name, original)
assert getattr(consumer, name) is hook
from dopplergeist import search, trial_prefix
from dopplergeist.data_access import FlightIndex
fixture = json.loads(Path(source).read_text())
witness = json.loads((Path(directory) / 'data/real-trial-prefix.json').read_text())['calls'][0]
events, measurements = matching.prepare_events(fixture['events'])
tracks = {track.id: track for track in FlightIndex(fixture['real_index']).lookup(
    witness['track_ids'], max_tracks=2000, max_samples=2000000)}
@matching._cache_ridge_fits
def run():
    frozen_events, frozen_measurements = matching._prepare_score_inputs(events, measurements)
    by_id = {event['event_id']: (event, measured) for event, measured in zip(frozen_events, frozen_measurements)}
    selected = [by_id[name] for name in witness['event_ids']]
    options = dict(tracks=[tracks[name] for name in witness['track_ids']],
        events=[pair[0] for pair in selected], measurements=[pair[1] for pair in selected],
        observer=np.asarray(witness['observer']), starts=np.asarray(witness['starts']),
        c=witness['c'], score_floor=witness['score_floor'], use_dual=witness['use_dual'],
        legacy_first_batch=witness['legacy_first_batch'])
    def batches():
        return matching._iter_acoustic_trials(options['tracks'], options['measurements'],
            options['observer'], options['starts'], options['c'])
    assert matching._prepared_score_tokens(options['measurements'], options['events']) is not None
    assert trial_prefix.request(**options, acoustic_batches=batches()) is None
    first = search._batched_ridge_trials(**options, acoustic_batches=batches())
    initial_calls = calls
    second = search._batched_ridge_trials(**options, acoustic_batches=batches())
    assert first == second
    assert trial_prefix.cache_stats()['hits'] == 0
    if name in ('_frequency_scale', '_native_validate_ridge_events'):
        assert calls > initial_calls > 0
run()
"""
    subprocess.run([sys.executable, "-c", code, module, name,
                    os.environ["DOPPLERGEIST_REAL_CPA_FIXTURE"], str(Path(__file__).parent)], check=True)


@pytest.mark.parametrize("target", ["matching", "search", "native_export"])
def test_real_prefix_rejects_changed_boolean_validator_aliases_and_export(recorded, monkeypatch, target):
    if target == "native_export":
        owner, name = matching._native_ridge_module, "valid_ridge_events"
        if owner is None or not hasattr(owner, name):
            pytest.skip("native boolean export is unavailable")
    else:
        owner = matching if target == "matching" else search
        name = "_native_validate_ridge_events"

    @matching._cache_ridge_fits
    def run():
        call = prepared_calls(recorded)[0]
        evaluate(call)
        original = getattr(owner, name)
        def custom(*args):
            return False if original is None else original(*args)
        monkeypatch.setattr(owner, name, custom)
        assert trial_prefix.request(**call, acoustic_batches=acoustic(call)) is None
    run()


def test_real_prefix_capacity_and_unsupported_trials(recorded, monkeypatch):
    @matching._cache_ridge_fits
    def run():
        call = prepared_calls(recorded)[0]
        original = identity(evaluate(call))
        memo = matching._ridge_fit_cache.get().prefix_memo
        monkeypatch.setattr(trial_prefix, "_MAX_ENTRIES", 1)
        shifted = dict(call, starts=np.nextafter(call["starts"], np.inf))
        evaluate(shifted)
        assert len(memo.entries) <= 1
        assert identity(evaluate(call)) == original
        for limit in (1, 0):
            monkeypatch.setattr(trial_prefix, "_MAX_BYTES", limit)
            assert identity(evaluate(call)) == original
            assert not memo.entries and memo.size == 0
        monkeypatch.setattr(trial_prefix, "_MAX_BYTES", 8 * 1024 * 1024)
        # The actual observed track has no support at this earlier clock. No
        # fabricated motion or audio is used for the failure-envelope control.
        unsupported = dict(call, starts=call["starts"] - 86400.)
        result = evaluate(unsupported)
        assert any(outcome[0] is not None or outcome[2] is not None for outcome in result[0])
        assert not memo.entries
    run()
