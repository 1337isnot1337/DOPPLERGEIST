"""Check ceiling reuse against the original validator using recorded ridge fits.

Metadata mutations exercise cache invalidation and conservative unknown-support
handling. They are software checks, not generated recordings or field evidence.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from dopplergeist import search
from dopplergeist.batch_ridge import first_event_fits
from dopplergeist.geometry import AcousticSupportError, ecef
from dopplergeist.matching import (
    _cache_ridge_fits, _frequency_scale, _iter_acoustic_trials, _ridge_fit_cache, prepare_events,
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
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    starts = start + np.linspace(-5, 5, 21)
    fits = None
    for event, measurement in zip(events, measurements):
        for track in (track for track in tracks if track.id.split(":")[0] in aircraft):
            try:
                batch = next(_iter_acoustic_trials([track], [measurement], observer, starts))
            except AcousticSupportError:
                continue
            if batch is not None:
                fits = first_event_fits(measurement, event, *batch)
                if fits is not None:
                    break
        if fits is not None:
            break
    if fits is None:
        raise RuntimeError("No supported batch exists for the supplied real receiver/flight hypotheses")
    limit = 3 * _frequency_scale(event)
    base = (fits[0], fits[0]["score"], fits[0]["f0_hz"], event, limit)
    checks = []
    calls = 0
    original_classify = search._ridge_trial_classification

    def counted(*values):
        nonlocal calls
        calls += 1
        return original_classify(*values)

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def same(name, values, miss=None):
        expected = search._association_event_ceiling_uncached(*values)
        before = calls
        actual = search._association_event_ceiling(*values)
        check(name, actual == expected or (np.isnan(actual) and np.isnan(expected)))
        if miss is not None:
            check(name + "_cache_behavior", calls == before + int(miss))

    @_cache_ridge_fits
    def exercise():
        outer = _ridge_fit_cache.get()
        for index, fit in enumerate(fits):
            values = (fit, fit["score"], fit["f0_hz"], event, limit)
            same(f"real_clock_{index}", values, True)
            same(f"copied_clock_{index}", deepcopy(values), False)
        for field in search._CEILING_FLOAT_FIELDS:
            changed = deepcopy(base)
            changed[0][field] = float(np.nextafter(changed[0][field], np.inf))
            same(field + "_mutation", changed, True)
        for field in ("sample_count", "independent_sample_count"):
            changed = deepcopy(base)
            changed[0][field] += 1
            same(field + "_mutation", changed, True)
        for field, value in (("optimizer_success", False), ("support_fraction", 0.0),
                             ("source_span_s", 0.0), ("drift_bound_hz", -1.0),
                             ("rmse_hz", -1.0), ("outlier_fraction", 2.0)):
            changed = deepcopy(base)
            changed[0][field] = value
            same(field + "_invalid", changed, True)
            check(field + "_conservative", search._association_event_ceiling(*changed) == 1.0)
        for index, name in ((1, "score_argument"), (2, "frequency_argument"), (4, "limit")):
            changed = list(deepcopy(base))
            changed[index] = float(np.nextafter(changed[index], np.inf))
            same(name + "_mutation", changed, True)
        for index in range(2):
            changed = deepcopy(base)
            changed[3]["f0_range_hz"][index] = float(np.nextafter(changed[3]["f0_range_hz"][index], np.inf))
            same(f"frequency_bound_{index}_mutation", changed, True)
        changed = deepcopy(base)
        changed[3].setdefault("quality", {})["source_drift_fraction"] = float(np.nextafter(
            changed[3]["quality"].get("source_drift_fraction", 0.02), np.inf))
        same("drift_fraction_mutation", changed, True)
        for value in (np.float32(base[1]), np.float64(base[1]), np.longdouble(base[1])):
            changed = list(deepcopy(base))
            changed[0]["score"] = changed[1] = value
            same(type(value).__name__ + "_bypass", changed, True)
            same(type(value).__name__ + "_repeated_bypass", changed, True)
        for field in ("support_fraction", "sample_count", "source_span_s"):
            changed = deepcopy(base)
            del changed[0][field]
            same(field + "_missing", changed, True)
            same(field + "_missing_bypass", changed, True)
        changed = list(deepcopy(base))
        changed[4] = None
        entries = len(outer.ceiling_entries)
        for _ in range(2):
            try:
                search._association_event_ceiling(*changed)
            except TypeError:
                checks.append("invalid_limit_exception")
            else:
                raise AssertionError("Invalid limit did not raise the original error")
        check("exceptions_not_cached", len(outer.ceiling_entries) == entries)

        @_cache_ridge_fits
        def nested():
            check("nested_context_is_independent", _ridge_fit_cache.get() is not outer)
            same("nested_first_lookup", base, True)
        nested()
        check("outer_context_restored", _ridge_fit_cache.get() is outer)
        same("outer_cached_fit_survives", base, False)

    def eviction():
        outer = _ridge_fit_cache.get()
        same("entry_limit_first", base, True)
        changed = list(deepcopy(base))
        changed[4] = float(np.nextafter(changed[4], np.inf))
        same("entry_limit_second", changed, True)
        check("entry_limit", len(outer.ceiling_entries) == 1)
        same("evicted_entry_recomputed", base, True)

    search._ridge_trial_classification = counted
    try:
        same("outside_context", base, True)
        exercise()
        check("context_reset", _ridge_fit_cache.get() is None)
        _cache_ridge_fits(eviction, max_entries=1)()
    finally:
        search._ridge_trial_classification = original_classify
    print(json.dumps({"passed": len(checks), "checks": checks, "event": event["event_id"],
                      "real_clock_fits": len(fits), "scope": "real-input ceiling cache regression"}, indent=2))


if __name__ == "__main__":
    main()
