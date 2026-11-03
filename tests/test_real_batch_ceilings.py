"""Whole-batch ceiling reuse on captured audio and historical ADS-B geometry."""
from copy import deepcopy
import json
from pathlib import Path
import pickle
import sys
import unittest
from unittest.mock import patch

import numpy as np

from dopplergeist import batch_ridge, matching, search


def recorded():
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    measurement = (matching.RidgeTimes(np.asarray(fixture["times"])),
                   np.asarray(fixture["ridge"]), np.asarray(fixture["weight"]), {})
    return measurement, fixture["event"], np.asarray(fixture["factors"]), np.asarray(fixture["emissions"])


def ceilings(fits, event, limit):
    if fits is None:
        return None
    return [search._association_event_ceiling_uncached(fit, fit["score"], fit["f0_hz"], event, limit)
            for fit in fits]


class RecordedBatchCeilings(unittest.TestCase):
    def test_reuse_enriches_fit_snapshot_and_copies_both_results(self):
        measurement, event, factors, emissions = recorded()
        limit = 3 * matching._frequency_scale(event)
        expected = batch_ridge.first_event_fits(measurement, event, factors, emissions)
        expected_ceilings = ceilings(expected, event, limit)
        calls = {"scalar_cache": 0, "validation": 0}
        native = matching._CANONICAL_NATIVE_EVENT_VALIDATOR
        if native is not None:
            self.assertTrue(all(native([fit], [fit["score"]], [fit["f0_hz"]], [event]) for fit in expected))
        expected_calls = ({"scalar_cache": len(expected), "validation": 0} if native is not None else
                          {"scalar_cache": 0, "validation": len(expected)})

        def profile(frame, action, unused):
            if action == "call":
                if frame.f_code is search._association_event_ceiling.__code__:
                    calls["scalar_cache"] += 1
                elif frame.f_code is search._association_event_ceiling_uncached.__code__:
                    calls["validation"] += 1

        @matching._cache_ridge_fits
        def run():
            cache = matching._ridge_fit_cache.get()
            self.assertEqual(batch_ridge.first_event_fits(measurement, event, factors, emissions), expected)
            self.assertIs(type(pickle.loads(next(iter(cache.batch_fit_entries.values())))), list)
            before = sys.getprofile()
            sys.setprofile(profile)
            try:
                fits, upper = batch_ridge._first_event_fits_with_ceilings(
                    measurement, event, factors, emissions, limit)
                self.assertEqual((fits, upper), (expected, expected_ceilings))
                self.assertEqual(calls, expected_calls)
                self.assertFalse(cache.ceiling_entries)
                fits[0].clear()
                upper[0] = -123.
                again = batch_ridge._first_event_fits_with_ceilings(
                    deepcopy(measurement), deepcopy(event), factors.copy(), emissions.copy(), limit)
                self.assertEqual(again, (expected, expected_ceilings))
                self.assertEqual(calls, expected_calls)
                self.assertEqual(batch_ridge.first_event_fits(measurement, event, factors, emissions), expected)
            finally:
                sys.setprofile(before)
            self.assertEqual(len(cache.batch_fit_entries), 1)
            self.assertEqual(cache.batch_fit_bytes,
                             sum(len(key) + len(value) for key, value in cache.batch_fit_entries.items()))
            self.assertLessEqual(cache.batch_fit_bytes, cache.batch_fit_limit)

        run()
        self.assertIsNone(matching._ridge_fit_cache.get())

    def test_changed_native_fitter_keeps_public_scalar_path_for_new_vectors(self):
        measurement, event, factors, emissions = recorded()
        limit = 3 * matching._frequency_scale(event)
        expected = batch_ridge.first_event_fits(measurement, event, factors, emissions)
        expected_ceilings = ceilings(expected, event, limit)
        hooks = []
        if matching._native_fit_irls is not None:
            hooks.append((matching, "_native_fit_irls"))
        for owner, name in hooks:
            with self.subTest(hook=name):
                @matching._cache_ridge_fits
                def run():
                    with patch.object(owner, name, wraps=getattr(owner, name)) as hook:
                        actual = batch_ridge._first_event_fits_with_ceilings(
                            measurement, event, factors, emissions, limit)
                        self.assertEqual(actual, (expected, expected_ceilings))
                        self.assertGreater(hook.call_count, 0)
                        self.assertEqual(bool(matching._ridge_fit_cache.get().ceiling_entries),
                                         matching._CANONICAL_NATIVE_EVENT_VALIDATOR is None)
                        # A complete cached vector retains its original behavior.
                        self.assertEqual(batch_ridge._first_event_fits_with_ceilings(
                            measurement, event, factors, emissions, limit), actual)
                run()

    def test_changed_boolean_aliases_and_export_do_not_reuse_a_ceiling_vector(self):
        measurement, event, factors, emissions = recorded()
        limit = 3 * matching._frequency_scale(event)
        expected = batch_ridge.first_event_fits(measurement, event, factors, emissions)
        expected_ceilings = ceilings(expected, event, limit)
        hooks = [(matching, "_native_validate_ridge_events"), (search, "_native_validate_ridge_events")]
        native_module = matching._native_ridge_module
        if native_module is not None and hasattr(native_module, "valid_ridge_events"):
            hooks.append((native_module, "valid_ridge_events"))
        for owner, name in hooks:
            with self.subTest(owner=owner.__name__, hook=name):
                @matching._cache_ridge_fits
                def run():
                    previous = batch_ridge._first_event_fits_with_ceilings(
                        measurement, event, factors, emissions, limit)
                    self.assertEqual(previous, (expected, expected_ceilings))
                    original = getattr(owner, name)
                    def custom(*args):
                        return False if original is None else original(*args)
                    with patch.object(owner, name, side_effect=custom) as hook:
                        for _ in range(2):
                            fits, upper = batch_ridge._first_event_fits_with_ceilings(
                                measurement, event, factors, emissions, limit)
                            self.assertEqual(fits, expected)
                            self.assertIsNone(upper)
                            self.assertEqual(ceilings(fits, event, limit), expected_ceilings)
                        if owner is search:
                            self.assertGreater(hook.call_count, 0)
                    self.assertEqual(batch_ridge._first_event_fits_with_ceilings(
                        measurement, event, factors, emissions, limit), previous)
                run()

    def test_event_limit_and_legacy_changes_keep_exact_scalar_ceilings(self):
        measurement, event, factors, emissions = recorded()
        limit = 3 * matching._frequency_scale(event)
        events = [event]
        for field in ("frequency_loss_scale_hz", "source_drift_fraction"):
            changed = deepcopy(event)
            original = matching._frequency_scale(event) if field.startswith("frequency") else .02
            changed.setdefault("quality", {})[field] = float(np.nextafter(original, np.inf))
            events.append(changed)
        for index in range(2):
            changed = deepcopy(event)
            changed["f0_range_hz"][index] = float(np.nextafter(changed["f0_range_hz"][index], np.inf))
            events.append(changed)

        @matching._cache_ridge_fits
        def run():
            for configured in events:
                for legacy in (False, True):
                    expected = batch_ridge._first_event_fits_uncached(
                        measurement, configured, factors, emissions, legacy_arithmetic=legacy)
                    for bound in (limit, float(np.nextafter(limit, np.inf))):
                        actual = batch_ridge._first_event_fits_with_ceilings(
                            measurement, configured, factors, emissions, bound, legacy_arithmetic=legacy)
                        self.assertEqual(actual, (expected, ceilings(expected, configured, bound)))

        run()

    def test_custom_classification_and_noncanonical_inputs_keep_per_row_path(self):
        measurement, event, factors, emissions = recorded()
        limit = 3 * matching._frequency_scale(event)

        class Custom(dict):
            pass

        @matching._cache_ridge_fits
        def run():
            expected = batch_ridge._first_event_fits_with_ceilings(
                measurement, event, factors, emissions, limit)
            with patch.object(search, "_ridge_trial_classification", return_value=("unknown", "custom")):
                fits, upper = batch_ridge._first_event_fits_with_ceilings(
                    measurement, event, factors, emissions, limit)
                self.assertEqual(fits, expected[0])
                self.assertIsNone(upper)
                self.assertEqual(ceilings(fits, event, limit), [1.] * len(fits))
            self.assertEqual(batch_ridge._first_event_fits_with_ceilings(
                measurement, event, factors, emissions, limit), expected)
            with np.errstate(all="raise"):
                fits, upper = batch_ridge._first_event_fits_with_ceilings(
                    measurement, event, factors, emissions, limit)
                self.assertEqual(fits, expected[0])
                self.assertIsNone(upper)
            for bound in (np.float64(limit), np.float32(limit), 1, 0., -0., float("nan"), float("inf")):
                fits, upper = batch_ridge._first_event_fits_with_ceilings(
                    measurement, event, factors, emissions, bound)
                self.assertEqual(fits, expected[0])
                self.assertIsNone(upper)
            for configured in (Custom(event), dict(event, quality=Custom(event["quality"]))):
                fits, upper = batch_ridge._first_event_fits_with_ceilings(
                    measurement, configured, factors, emissions, limit)
                self.assertEqual(fits, expected[0])
                self.assertIsNone(upper)
            with patch.object(batch_ridge, "first_event_fits", return_value=None) as fallback:
                self.assertEqual(batch_ridge._first_event_fits_with_ceilings(
                    measurement, event, factors, emissions, limit), (None, None))
                fallback.assert_called_once()

        run()

    def test_shared_byte_entry_budgets_and_nested_scopes(self):
        measurement, event, factors, emissions = recorded()
        limit = 3 * matching._frequency_scale(event)
        expected = batch_ridge.first_event_fits(measurement, event, factors, emissions)

        def run():
            cache = matching._ridge_fit_cache.get()
            batch_ridge._first_event_fits_with_ceilings(measurement, event, factors, emissions, limit)
            batch_ridge._first_event_fits_with_ceilings(measurement, event, factors[::-1], emissions[::-1], limit)
            self.assertEqual(len(cache.batch_fit_entries), 1)
            actual = batch_ridge._first_event_fits_with_ceilings(measurement, event, factors, emissions, limit)
            self.assertEqual(actual, (expected, ceilings(expected, event, limit)))

            @matching._cache_ridge_fits
            def nested():
                self.assertIsNot(matching._ridge_fit_cache.get(), cache)
                self.assertEqual(batch_ridge._first_event_fits_with_ceilings(
                    measurement, event, factors, emissions, limit), actual)
            nested()
            self.assertIs(matching._ridge_fit_cache.get(), cache)
            cache.batch_fit_entries.clear()
            cache.batch_fit_bytes = 0
            for size in (1, 0):
                cache.batch_fit_limit = size
                fits, upper = batch_ridge._first_event_fits_with_ceilings(
                    measurement, event, factors, emissions, limit)
                self.assertEqual(fits, expected)
                self.assertEqual(upper, ceilings(expected, event, limit) if size else None)
                self.assertEqual(cache.batch_fit_bytes, 0)
                self.assertFalse(cache.batch_fit_entries)

        matching._cache_ridge_fits(run, max_entries=1)()


if __name__ == "__main__":
    unittest.main()
