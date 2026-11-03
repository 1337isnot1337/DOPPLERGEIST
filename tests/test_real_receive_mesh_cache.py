"""Receive-clock mesh reuse on recorded ridges and historical aircraft paths."""
import json
import os
from pathlib import Path

import numpy as np
import pytest

from dopplergeist import matching
from dopplergeist.data_access import FlightIndex


@pytest.fixture(scope="module")
def recorded():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the recorded CPA diagnostic")
    fixture = json.loads(Path(source).read_text())
    witness = json.loads((Path(__file__).parent / "data/real-trial-prefix.json").read_text())["calls"][0]
    events, measurements = matching.prepare_events(fixture["events"])
    measured = next(value for event, value in zip(events, measurements)
                    if event["event_id"] == witness["event_ids"][0])
    times = measured[0].time[np.isfinite(measured[0].time) & np.isfinite(measured[1]) & (measured[2] > 0)]
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(witness["track_ids"][:2])}
    return ([tracks[name] for name in witness["track_ids"][:2]],
            np.asarray(witness["observer"]), np.asarray(witness["starts"]), times, witness["c"])


def assert_same(actual, expected):
    for observed, reference in zip(actual, expected):
        np.testing.assert_array_equal(observed, reference)


def uncached(track, observer, starts, times, c):
    cache = matching._RidgeFitCache(1)
    cache.receive_mesh_limit = cache.acoustic_limit = 0
    return cache.acoustic_batch(track, observer, starts, times, c)


def test_recorded_mesh_reuses_clocks_across_aircraft_with_exact_outputs(recorded):
    tracks, observer, starts, times, c = recorded
    expected = [uncached(track, observer, starts, times, c) for track in tracks]
    cache = matching._RidgeFitCache(4)
    for track, reference in zip(tracks, expected):
        assert_same(cache.acoustic_batch(track, observer, starts, times, c), reference)
    assert cache.receive_mesh_hits == cache.receive_mesh_misses == 1
    assert len(cache.receive_mesh_entries) == 1


def test_recorded_mesh_gives_custom_hooks_fresh_writable_arguments(recorded):
    tracks, observer, starts, times, c = recorded
    cache = matching._RidgeFitCache(4)
    cache.acoustic_limit = 0
    received = []

    class ObservedHook:
        def __init__(self, track):
            self.track = track

        def acoustic(self, values, observer, c):
            assert values.flags.writeable
            result = self.track.acoustic(values, observer, c)
            received.append(values.copy())
            # Mutating a custom hook's argument after evaluating the real path
            # must not change either cached timestamps or future hook inputs.
            values[:] = np.nextafter(values, np.inf)
            return result

    for track in (*tracks, tracks[0]):
        assert_same(cache.acoustic_batch(ObservedHook(track), observer, starts, times, c),
                    uncached(track, observer, starts, times, c))
    assert cache.receive_mesh_hits == 2
    assert all(np.array_equal(values, received[0]) for values in received)
    starts_before, times_before = starts.copy(), times.copy()
    output = cache.acoustic_batch(tracks[0], observer, starts, times, c)
    output[0][:] = np.nan
    output[1][:] = np.nan
    assert_same(cache.acoustic_batch(tracks[0], observer, starts, times, c),
                uncached(tracks[0], observer, starts, times, c))
    assert_same((starts, times), (starts_before, times_before))


@pytest.mark.parametrize("changed", ["clock", "time", "layout", "policy"])
def test_recorded_mesh_keys_and_fallbacks_keep_current_input_behavior(recorded, changed):
    tracks, observer, starts, times, c = recorded
    cache = matching._RidgeFitCache(4)
    cache.acoustic_limit = 0
    cache.acoustic_batch(tracks[0], observer, starts, times, c)
    starts, times = starts.copy(), times.copy()
    if changed == "clock":
        starts[0] = np.nextafter(starts[0], np.inf)
    elif changed == "time":
        times[0] = np.nextafter(times[0], np.inf)
    elif changed == "layout":
        starts, times = starts[::-1], times[::-1]
    settings = {"all": "raise"} if changed == "policy" else {}
    with np.errstate(**settings):
        assert_same(cache.acoustic_batch(tracks[0], observer, starts, times, c),
                    uncached(tracks[0], observer, starts, times, c))
    assert cache.receive_mesh_hits == 0
    assert cache.receive_mesh_misses == (2 if changed in ("clock", "time") else 1)


def test_recorded_mesh_cache_obeys_entry_and_byte_limits(recorded):
    tracks, observer, starts, times, c = recorded
    cache = matching._RidgeFitCache(1)
    cache.acoustic_limit = 0
    for clocks in (starts, starts[:11], starts):
        assert_same(cache.acoustic_batch(tracks[0], observer, clocks, times, c),
                    uncached(tracks[0], observer, clocks, times, c))
        assert len(cache.receive_mesh_entries) == 1
        assert cache.receive_mesh_bytes <= cache.receive_mesh_limit
        assert cache.receive_mesh_bytes == sum(value[2] for value in cache.receive_mesh_entries.values())
    assert cache.receive_mesh_hits == 0
    for limit in (0, 1):
        cache = matching._RidgeFitCache(4)
        cache.acoustic_limit = 0
        cache.receive_mesh_limit = limit
        for track in tracks:
            assert_same(cache.acoustic_batch(track, observer, starts, times, c),
                        uncached(track, observer, starts, times, c))
        assert not cache.receive_mesh_entries
        assert cache.receive_mesh_bytes == cache.receive_mesh_hits == 0


@pytest.mark.parametrize("changed", ["unique", "key"])
def test_recorded_mesh_does_not_hide_replaced_helpers(recorded, monkeypatch, changed):
    tracks, observer, starts, times, c = recorded
    cache = matching._RidgeFitCache(4)
    cache.acoustic_limit = 0
    cache.acoustic_batch(tracks[0], observer, starts, times, c)
    owner, name = (np, "unique") if changed == "unique" else (matching, "_fit_argument_key")
    original = getattr(owner, name)
    calls = []

    def custom(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, custom)
    actual = cache.acoustic_batch(tracks[1], observer, starts, times, c)
    assert calls
    assert cache.receive_mesh_hits == 0
    assert cache.receive_mesh_misses == 1
    assert_same(actual, uncached(tracks[1], observer, starts, times, c))
