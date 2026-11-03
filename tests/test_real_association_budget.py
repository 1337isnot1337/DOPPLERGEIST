"""Regression from actual ADS-B CPAs and automatically proposed real-audio groups."""
import json
import math
from pathlib import Path

import pandas as pd
import pytest

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


def test_real_silence_filter_remains_within_work_budget():
    fixture = json.loads((Path(__file__).parent / 'data' / 'reference-cpa-real.json').read_text())
    candidates, counts = association_candidates(pd.DataFrame(fixture['cpa_rows']), fixture['events'],
                                                 offset_tolerance_s=5, max_candidates=20000,
                                                 silence={'edge_margin_s': 60})
    assert len(candidates) == 1590
    assert counts['work_units'] <= 400000


@pytest.mark.parametrize('silence', [None, {'edge_margin_s': 60}])
def test_real_anchor_partitions_preserve_candidates_and_clock_intervals(silence):
    fixture = json.loads((Path(__file__).parent / 'data' / 'reference-cpa-real.json').read_text())
    events = fixture['events']
    table = pd.DataFrame(fixture['cpa_rows'])
    kwargs = dict(offset_tolerance_s=5, max_candidates=20000, silence=silence)
    baseline, _ = association_candidates(table, events, **kwargs)

    def anchor(candidate):
        return candidate['passes'][0]['receive_time'] - events[candidate['event_indices'][0]]['cpa_receive_s']

    def records(candidates):
        return sorted(json.dumps(candidate, sort_keys=True) for candidate in candidates)

    anchors = sorted({anchor(candidate) for candidate in baseline})
    pivot = anchors[len(anchors) // 2]
    expected = records(baseline)
    for boundary in (math.nextafter(pivot, -math.inf), pivot, math.nextafter(pivot, math.inf)):
        left, _ = association_candidates(table, events, anchor_window=(-math.inf, boundary), **kwargs)
        right, _ = association_candidates(table, events, anchor_window=(boundary, math.inf), **kwargs)
        assert all(anchor(candidate) < boundary for candidate in left)
        assert all(anchor(candidate) >= boundary for candidate in right)
        assert records(left + right) == expected

    for invalid in ((1, 1), (1, 0), (math.nan, 1)):
        with pytest.raises(ValueError, match='Anchor window'):
            association_candidates(table, events, anchor_window=invalid, **kwargs)
