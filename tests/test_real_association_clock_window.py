"""Clock pruning checked against archived real flight and acoustic observations."""
import json
from pathlib import Path

import pandas as pd

from dopplergeist.matching import association_candidates
from dopplergeist.tiled_search import _association_clock_window


def real_associations():
    path = Path(__file__).parent / "data/reference-cpa-real.json"
    recorded = json.loads(path.read_text())
    table = pd.DataFrame(recorded["cpa_rows"])
    candidates, counts = association_candidates(table, recorded["events"])
    return table, recorded["events"], candidates, counts


def scheduled_intervals(candidates, window, sweep_s):
    """Join the same observed association identities after the clock restriction."""
    retained = {}
    for candidate in candidates:
        lower, upper = candidate["recording_start_bounds_s"]
        interval = (max(lower - sweep_s, window[0]), min(upper + sweep_s, window[1]))
        if interval[0] > interval[1]:
            continue
        identity = (tuple(candidate["event_indices"]),
                    tuple((row["flight_id"], row["emission_time"]) for row in candidate["passes"]))
        assert identity not in retained
        retained[identity] = interval
    return retained


def bounded_associations(table, events, window, sweep_s):
    center, tolerance = _association_clock_window(window, sweep_s)
    return association_candidates(table, events, time_origin=center, time_tolerance_s=tolerance)


def test_real_recording_window_avoids_unrelated_clock_work_without_losing_trials():
    table, events, original, original_counts = real_associations()
    # Historical source-informed development clock; not independent field truth.
    window, sweep_s = (1788898640.0, 1788898660.0), 5.0
    bounded, bounded_counts = bounded_associations(table, events, window, sweep_s)
    expected = scheduled_intervals(original, window, sweep_s)
    assert len(original) == 10549 and len(expected) == 26
    assert scheduled_intervals(bounded, window, sweep_s) == expected
    assert bounded_counts["work_units"] < original_counts["work_units"] / 10


def test_real_association_clock_endpoints_remain_inclusive():
    table, events, original, _ = real_associations()
    # Use interval endpoints from measured passages, including subsecond Unix
    # times. No acoustic sample, trajectory, event or flight identity is changed.
    for candidate in (original[0], original[5274], original[-1]):
        lower, upper = candidate["recording_start_bounds_s"]
        for sweep_s in (0.0, 5.0):
            for instant in (lower - sweep_s, upper + sweep_s):
                window = (instant, instant)
                expected = scheduled_intervals(original, window, sweep_s)
                assert expected
                bounded, _ = bounded_associations(table, events, window, sweep_s)
                assert scheduled_intervals(bounded, window, sweep_s) == expected
