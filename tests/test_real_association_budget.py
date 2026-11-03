"""Regression from actual ADS-B CPAs and automatically proposed real-audio groups."""
import json
from pathlib import Path

import pandas as pd

from dopplergeist.matching import association_candidates


def test_real_passages_fit_association_budget_without_losing_hypotheses():
    fixture = json.loads((Path(__file__).parent / 'data' / 'reference-cpa-real.json').read_text())
    candidates, counts = association_candidates(pd.DataFrame(fixture['cpa_rows']), fixture['events'],
                                                 offset_tolerance_s=5, max_candidates=20000)
    # Independently recorded from the previous traversal with its work budget
    # raised for this diagnostic only. Input location is not the recording truth.
    assert len(candidates) == 10549
    assert counts['work_units'] <= 400000
    for candidate in candidates:
        intervals = []
        for event_index, passage in zip(candidate['event_indices'], candidate['passes']):
            event = fixture['events'][event_index]
            center = passage['receive_time'] - event['cpa_receive_s']
            tolerance = event['quality']['cpa_tolerance_s'] + 2.5
            intervals.append((center - tolerance, center + tolerance))
        assert candidate['recording_start_bounds_s'] == [max(lo for lo, _ in intervals),
                                                        min(hi for _, hi in intervals)]
    for index, event_indices, flight_ids in (
        (0, [0, 1, 2, 4, 5], ['06a128', 'ac79b1', 'a2587b', 'a4b49c', 'a97797']),
        (5274, [2, 5, 6, 7, 8], ['a82a7f', 'ada36a', 'a2db21', 'a8b805', 'a396a9']),
        (10548, [14], ['ae2660']),
    ):
        assert candidates[index]['event_indices'] == event_indices
        assert [p['flight_id'] for p in candidates[index]['passes']] == flight_ids
