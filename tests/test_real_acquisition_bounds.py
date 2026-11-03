"""Optional regression using saved discovery results from real recordings."""
import json
import os
from pathlib import Path

import pytest

from dopplergeist.automatic import _earliest_emission, _latest_emission
from dopplergeist.matching import prepare_events


def test_real_events_keep_the_full_refinement_and_cpa_envelopes():
    source = os.environ.get("DOPPLERGEIST_REAL_DISCOVERY_RESULTS")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_DISCOVERY_RESULTS to real completed job outputs")
    checked = 0
    for path in sorted(Path(source).glob("clip-*/**/result.json")):
        result = json.loads(path.read_text())
        events = result.get("events", [])
        if not events:
            continue
        prepared, _ = prepare_events(events)
        # Bounds are translation invariant; these are offsets, not a claimed
        # UTC clock for the recordings.
        acquisition = _earliest_emission(0., prepared, 20000., 343., {})
        refinement = min(e["start_s"] for e in prepared) - 20000. / 300. - 120.
        cpa = min(e["cpa_receive_s"] - e["quality"]["cpa_tolerance_s"] for e in prepared)
        cpa -= 2.5 + 5. + 20000. / 343. + 30.
        assert acquisition <= refinement
        assert acquisition <= cpa
        duration = result["recording"]["duration_s"]
        latest = _latest_emission(0., duration, prepared, {})
        assert latest >= duration + 30
        assert latest >= max(e["end_s"] for e in prepared) + 120
        latest_cpa = max(e["cpa_receive_s"] + e["quality"]["cpa_tolerance_s"] for e in prepared)
        assert latest >= latest_cpa + 2.5 + 5 + 30
        checked += 1
    assert checked > 0, "No real proposal-bearing completed jobs found"
