"""Keep saved first-group arithmetic separate in the recorded batch cache."""
import json
from pathlib import Path

import numpy as np

from dopplergeist import batch_ridge, matching


def test_recorded_legacy_and_current_batches_do_not_share_cache_entries():
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    measurement = (matching.RidgeTimes(np.asarray(fixture["times"])),
                   np.asarray(fixture["ridge"]), np.asarray(fixture["weight"]), {})
    event = fixture["event"]
    factors, emissions = np.asarray(fixture["factors"]), np.asarray(fixture["emissions"])
    canonical = batch_ridge._first_event_fits_uncached(measurement, event, factors, emissions)
    legacy = batch_ridge._first_event_fits_uncached(measurement, event, factors, emissions,
                                                  legacy_arithmetic=True)

    @matching._cache_ridge_fits
    def check():
        for _ in range(2):
            assert batch_ridge.first_event_fits(measurement, event, factors, emissions) == canonical
            assert batch_ridge.first_event_fits(measurement, event, factors, emissions,
                                               legacy_arithmetic=True) == legacy
        assert len(matching._ridge_fit_cache.get().batch_fit_entries) == int(canonical is not None) + int(legacy is not None)

    check()
