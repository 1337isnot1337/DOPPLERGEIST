"""Select the fitter in fresh processes without changing recorded fit results."""
import json
import os
from pathlib import Path
import subprocess
import sys

from dopplergeist import matching


_RECORDED_FITS = """
import json
from pathlib import Path
import sys
import numpy as np
from dopplergeist import batch_ridge, matching

fixture = json.loads(Path(sys.argv[1]).read_text())
measurement = (matching.RidgeTimes(np.asarray(fixture['times'])),
               np.asarray(fixture['ridge']), np.asarray(fixture['weight']), {})
event = fixture['event']
factors, emissions = np.asarray(fixture['factors']), np.asarray(fixture['emissions'])
arguments = (None, None, measurement, 0., event['f0_range_hz'], 343.,
             matching._frequency_scale(event), event['quality'].get('source_drift_fraction', 0.02))
fits = [matching._fit_ridge_uncached(*arguments, acoustic_result=(factor, emitted))
        for factor, emitted in zip(factors, emissions)]
legacy = batch_ridge._first_event_fits_uncached(measurement, event, factors[1:2],
                                             emissions[1:2], legacy_arithmetic=True)
print(json.dumps({'backend': matching.RIDGE_FIT_BACKEND,
                  'native': matching._native_fit_irls is not None,
                  'fits': fits, 'legacy': legacy}, sort_keys=True))
"""


def _run_backend(choice, program=_RECORDED_FITS):
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    package_parent = Path(matching.__file__).resolve().parents[1]
    environment["PYTHONPATH"] = os.pathsep.join((str(package_parent), environment.get("PYTHONPATH", "")))
    if choice is None:
        environment.pop("DOPPLERGEIST_RIDGE_BACKEND", None)
    else:
        environment["DOPPLERGEIST_RIDGE_BACKEND"] = choice
    return subprocess.run([sys.executable, "-c", program,
                           str(root / "tests/data/real-ridge-batch-arithmetic.json")],
                          env=environment, text=True, capture_output=True, timeout=30)


def test_python_backend_selector_preserves_recorded_fits_and_identity():
    outputs = []
    for choice in (None, "auto", "python"):
        result = _run_backend(choice)
        assert result.returncode == 0, result.stderr
        outputs.append(json.loads(result.stdout))
    default, automatic, python = outputs
    assert default == automatic
    assert python["backend"] == "python-irls-v1"
    assert python["native"] is False
    assert automatic["native"] is (matching._native_fit_irls is not None)
    assert automatic["native"] == automatic["backend"].startswith("native-c-irls-v2-pairwise:")
    assert automatic["fits"] == python["fits"]
    assert automatic["legacy"] is python["legacy"] is None


def test_unknown_backend_selector_fails_clearly():
    result = _run_backend("native", "from dopplergeist import matching")
    assert result.returncode != 0
    assert "DOPPLERGEIST_RIDGE_BACKEND must be 'auto' or 'python'" in result.stderr
