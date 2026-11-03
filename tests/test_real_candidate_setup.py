"""Candidate preparation controls from recorded reference inputs."""
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from dopplergeist import matching, search


def recorded():
    directory = Path(__file__).parent / "data"
    ridge = json.loads((directory / "real-ridge-batch-arithmetic.json").read_text())
    point = json.loads((directory / "real-search-workloads.json").read_text())["cases"]["previous-fit"]["point"]
    measurement = (matching.RidgeTimes(np.asarray(ridge["times"])),
                   np.asarray(ridge["ridge"]), np.asarray(ridge["weight"]), {})
    return ridge["event"], measurement, tuple(point[name] for name in ("lat", "lon", "elev_m"))


def test_recorded_scalar_observer_reuse_preserves_bits_and_array_ownership():
    event, measurement, coordinates = recorded()

    @matching._cache_ridge_fits
    def run():
        matching._prepare_score_inputs([event], [measurement])
        expected = search.ecef(*coordinates)
        first, second = search._candidate_observer(*coordinates), search._candidate_observer(*coordinates)
        assert first.tobytes() == second.tobytes() == expected.tobytes()
        assert first is not second and first.flags.writeable and second.flags.writeable
        first[:] = 0.
        assert search._candidate_observer(*coordinates).tobytes() == expected.tobytes()
        cache = matching._ridge_fit_cache.get()
        assert len(cache.observer_entries) == 1
        cache.max_entries = 1
        for index in range(3):
            changed = list(coordinates)
            changed[index] = float(np.nextafter(changed[index], np.inf))
            actual = search._candidate_observer(*changed)
            assert actual.tobytes() == search.ecef(*changed).tobytes()
            assert len(cache.observer_entries) == 1
    run()


def test_recorded_observer_custom_function_remains_stateful(monkeypatch):
    event, measurement, coordinates = recorded()
    original = search.ecef
    calls = 0

    def custom(*values):
        nonlocal calls
        calls += 1
        return original(*values) + calls

    @matching._cache_ridge_fits
    def run():
        matching._prepare_score_inputs([event], [measurement])
        search._candidate_observer(*coordinates)
        monkeypatch.setattr(search, "ecef", custom)
        first, second = search._candidate_observer(*coordinates), search._candidate_observer(*coordinates)
        assert calls == 2
        np.testing.assert_array_equal(second - first, np.ones(3))
    run()


def test_recorded_observer_respects_a_hook_installed_before_search_import():
    code = """
import json
from pathlib import Path
import sys
import numpy as np
from dopplergeist import geometry
original, calls = geometry.ecef, 0
def custom(*values):
    global calls
    calls += 1
    return original(*values) + calls
geometry.ecef = custom
from dopplergeist import matching, search
directory = Path(sys.argv[1])
ridge = json.loads((directory / 'real-ridge-batch-arithmetic.json').read_text())
point = json.loads((directory / 'real-search-workloads.json').read_text())['cases']['previous-fit']['point']
measurement = (matching.RidgeTimes(np.asarray(ridge['times'])), np.asarray(ridge['ridge']),
               np.asarray(ridge['weight']), {})
@matching._cache_ridge_fits
def run():
    matching._prepare_score_inputs([ridge['event']], [measurement])
    values = tuple(point[name] for name in ('lat', 'lon', 'elev_m'))
    first, second = search._candidate_observer(*values), search._candidate_observer(*values)
    assert calls == 2
    np.testing.assert_array_equal(second - first, np.ones(3))
run()
"""
    subprocess.run([sys.executable, "-c", code, str(Path(__file__).parent / "data")], check=True)


@pytest.mark.parametrize("changed", ["bounds", "scale", "shape"])
def test_recorded_score_floor_validation_keeps_changed_input_failures(changed, monkeypatch):
    event, measurement, _ = recorded()

    @matching._cache_ridge_fits
    def run():
        events, measurements = matching._prepare_score_inputs([event], [measurement])
        assert matching._prepared_score_tokens(measurements, events) is not None
        assert search._validate_score_ceiling_inputs(events, measurements) is None
        if changed == "bounds":
            events[0]["f0_range_hz"][0] = float("nan")
        elif changed == "scale":
            events[0]["quality"]["frequency_loss_scale_hz"] = -1.
        else:
            measurements[0][0].time.shape = (1, -1)
        with pytest.raises(ValueError) as actual:
            search._validate_score_ceiling_inputs(events, measurements)
        monkeypatch.setattr(matching, "_prepared_score_tokens", lambda *args: None)
        with pytest.raises(ValueError) as expected:
            search._validate_score_ceiling_inputs(events, measurements)
        assert str(actual.value) == str(expected.value)
    run()
