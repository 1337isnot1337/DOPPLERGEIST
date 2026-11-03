"""Check exact batch-cache behavior using recorded ridges and flight tracks.

This is a software regression check, not a location-accuracy experiment. Input
mutation checks change copies by one ULP solely to test cache invalidation.
No recording or trajectory is generated.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from dopplergeist import batch_ridge
from dopplergeist.batch_ridge import first_event_fits
from dopplergeist.geometry import AcousticSupportError, ecef
from dopplergeist.matching import (
    _cache_ridge_fits, _frequency_scale,
    _iter_acoustic_trials, _ridge_fit_cache, prepare_events,
)
from dopplergeist.tracks import load_tracks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", required=True, type=Path)
    parser.add_argument("--tracks", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    events, measurements = prepare_events(json.loads(args.discovery.read_text())["events"])
    saved = json.loads(args.candidate.read_text())
    point = saved.get("best", saved)
    start = point["recording_start_time_s"]
    tracks, _ = load_tracks(args.tracks, time_range=(start - 120, start + max(e["end_s"] for e in events) + 120))
    aircraft = {identifier.split(":")[0] for identifier in point["flight_ids"]}
    chosen = [track for track in tracks if track.id.split(":")[0] in aircraft]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    starts = start + np.linspace(-5, 5, 21)
    uncached = batch_ridge._first_event_fits_uncached
    inputs = None
    for event, measurement in zip(events, measurements):
        for track in chosen:
            try:
                batch = next(_iter_acoustic_trials([track], [measurement], observer, starts))
            except AcousticSupportError:
                continue
            if batch is not None and uncached(measurement, event, *batch) is not None:
                inputs = measurement, event, *batch
                break
        if inputs is not None:
            break
    if inputs is None:
        raise RuntimeError("No supported batch exists for the supplied real receiver/flight hypotheses")

    calls = 0
    checks = []

    def counted(*values, **options):
        nonlocal calls
        calls += 1
        return uncached(*values, **options)

    def cached_for(function):
        # Exercise the production cache through its private fitter hook. No
        # second cache or compatibility storage is introduced by this checker.
        def call(*values, **options):
            previous = batch_ridge._first_event_fits_uncached
            batch_ridge._first_event_fits_uncached = function
            try:
                return first_event_fits(*values, **options)
            finally:
                batch_ridge._first_event_fits_uncached = previous
        return call

    cached = cached_for(counted)

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    expected = uncached(*inputs)
    check("no_context_result", cached(*inputs) == expected)
    check("no_context_bypass", calls == 1 and _ridge_fit_cache.get() is None)

    @_cache_ridge_fits
    def check_context():
        outer = _ridge_fit_cache.get()
        initial = calls
        first = cached(*inputs)
        second = cached(*deepcopy(inputs))
        check("equal_copies_hit", calls == initial + 1 and first == second == expected)
        first[0]["score"] = 12345.0
        second[0]["f0_hz"] = 0.0
        check("diagnostic_copies_are_independent", cached(*inputs) == expected)
        check("serialized_byte_bound", 0 < outer.batch_fit_bytes <= outer.batch_fit_limit)
        check("serialized_byte_accounting", outer.batch_fit_bytes == sum(
            len(key) + len(snapshot) for key, snapshot in outer.batch_fit_entries.items()))

        def alternate(*values, **options):
            return counted(*values, **options)

        before = calls
        check("different_function_result", cached_for(alternate)(*inputs) == expected)
        check("different_function_misses", calls == before + 1)
        before = calls
        check("restored_function_recomputes", cached(*inputs) == expected and calls == before + 1)
        check("restored_function_warm_hit", cached(*inputs) == expected and calls == before + 1)

        for index, name in enumerate(("times", "ridge", "weights", "factors", "emissions")):
            changed = deepcopy(inputs)
            array = ((changed[0][0].time, changed[0][1], changed[0][2], changed[2], changed[3])[index])
            array.flat[0] = np.nextafter(array.flat[0], np.inf)
            before = calls
            check(name + "_mutation_result", cached(*changed) == uncached(*changed))
            check(name + "_mutation_misses", calls == before + 1)

        for name in ("bounds", "sigma", "fraction"):
            changed = deepcopy(inputs)
            event = changed[1]
            if name == "bounds":
                event["f0_range_hz"] = list(event["f0_range_hz"])
                event["f0_range_hz"][0] = float(np.nextafter(event["f0_range_hz"][0], np.inf))
            elif name == "sigma":
                event.setdefault("quality", {})["frequency_loss_scale_hz"] = float(np.nextafter(_frequency_scale(event), np.inf))
            else:
                event.setdefault("quality", {})["source_drift_fraction"] = float(np.nextafter(event["quality"].get("source_drift_fraction", 0.02), np.inf))
            before = calls
            check(name + "_mutation_result", cached(*changed) == uncached(*changed))
            check(name + "_mutation_misses", calls == before + 1)

        changed = list(deepcopy(inputs))
        changed[2] = changed[2].astype(changed[2].dtype.newbyteorder(">"))
        before = calls
        check("dtype_result", cached(*changed) == uncached(*changed))
        check("dtype_misses", calls == before + 1)
        changed = [*inputs[:2], inputs[2][::-1], inputs[3][::-1]]
        before = calls
        check("row_order_result", cached(*changed) == uncached(*changed))
        check("row_order_misses", calls == before + 1)
        changed = [*inputs[:2], np.asfortranarray(inputs[2]), np.asfortranarray(inputs[3])]
        before = calls
        check("fortran_layout_result", cached(*changed) == uncached(*changed))
        check("fortran_layout_misses", calls == before + 1)
        changed = [*inputs[:2], inputs[2].tolist(), inputs[3].tolist()]
        before = calls
        check("custom_representation_result", cached(*changed) == cached(*changed) == expected)
        check("custom_representation_bypasses", calls == before + 2)
        before = calls
        check("measurement_iterator_result", cached(iter(inputs[0]), *inputs[1:]) == expected)
        check("measurement_iterator_bypasses", calls == before + 1)
        changed = list(deepcopy(inputs))
        measurement = list(changed[0])
        measurement[0] = SimpleNamespace(time=measurement[0].time)
        changed[0] = measurement
        before = calls
        check("custom_time_container_result", cached(*changed) == cached(*changed) == expected)
        check("custom_time_container_bypasses", calls == before + 2)

        missing = [*inputs[:2], inputs[2][:0], inputs[3][:0]]
        before = calls
        entries = len(outer.batch_fit_entries)
        check("fallback_none", cached(*missing) is None and cached(*missing) is None)
        check("fallback_not_cached", calls == before + 2 and len(outer.batch_fit_entries) == entries)
        malformed = deepcopy(inputs)
        malformed[0][0].time = malformed[0][0].time[:2]
        before = calls
        for _ in range(2):
            try:
                cached(*malformed)
            except ValueError:
                pass
            else:
                raise AssertionError("Malformed measurement did not raise")
        check("exceptions_not_cached", calls == before + 2 and len(outer.batch_fit_entries) == entries)

        @_cache_ridge_fits
        def nested():
            check("nested_context_is_independent", _ridge_fit_cache.get() is not outer)
            before = calls
            check("nested_fit_result", cached(*inputs) == expected)
            check("nested_fit_misses", calls == before + 1)
            raise RuntimeError("Check context restoration after an exception")

        try:
            nested()
        except RuntimeError:
            pass
        check("nested_context_restored", _ridge_fit_cache.get() is outer)
        before = calls
        check("outer_fit_survives", cached(*inputs) == expected and calls == before)

    check_context()
    check("context_reset", _ridge_fit_cache.get() is None)

    def eviction():
        cache = _ridge_fit_cache.get()
        first = deepcopy(inputs)
        second = deepcopy(inputs)
        second[2][0, 0] = np.nextafter(second[2][0, 0], np.inf)
        check("eviction_first_result", cached(*first) == uncached(*first))
        check("eviction_second_result", cached(*second) == uncached(*second))
        check("entry_limit", len(cache.batch_fit_entries) == 1)
        before = calls
        check("evicted_fit_recomputed", cached(*first) == uncached(*first) and calls == before + 1)
        cache.batch_fit_entries.clear()
        cache.batch_fit_bytes = 0
        cache.batch_fit_limit = 1
        before = calls
        check("oversized_fits_bypass", cached(*first) == cached(*first) == expected and calls == before + 2)
        check("oversized_fits_not_stored", len(cache.batch_fit_entries) == cache.batch_fit_bytes == 0)

    _cache_ridge_fits(eviction, max_entries=1)()
    print(json.dumps({"checks": checks, "passed": len(checks), "recorded_groups": len(events),
                      "selected_event": inputs[1].get("event_id"), "clock_rows": len(inputs[2]),
                      "scope": "real-input cache regression; no location-accuracy claim"}, indent=2))


if __name__ == "__main__":
    main()
