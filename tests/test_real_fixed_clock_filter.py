"""Fixed-clock boundary regression using an observed ADS-B passage and audio proposal."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist.matching import association_candidates
from dopplergeist.search import pair_candidates


@pytest.mark.parametrize("find_candidates", [association_candidates, pair_candidates])
def test_real_passage_is_kept_at_inclusive_clock_endpoints(find_candidates):
    event = {'cpa_receive_s': 301.25, 'speed_range_mps': [1.0, 308.7],
             'slant_range_m': [1.0, 20000.0], 'quality': {'cpa_tolerance_s': 7.25}}
    passage = {'point_id': 0, 'flight_id': '06a128', 'emission_time': 1788899665.5239854,
               'receive_time': 1788899668.4499502, 'distance_m': 1003.605901071673,
               'speed_mps': 88.57298283028696}
    center = passage['receive_time'] - event['cpa_receive_s']
    tolerance = event['quality']['cpa_tolerance_s'] + 2.5
    left, right = center - tolerance, center + tolerance
    for clock, expected in ((np.nextafter(left, -np.inf), False), (left, True),
                            (np.nextafter(left, np.inf), True), (np.nextafter(right, -np.inf), True),
                            (right, True), (np.nextafter(right, np.inf), False)):
        candidates, _ = find_candidates(pd.DataFrame([passage]), [event],
                                        offset_tolerance_s=5, time_origin=clock,
                                        time_tolerance_s=0)
        assert bool(candidates) is expected

    # The declared clock window may itself span multiple seconds.
    for clock, expected in ((np.nextafter(left - 3, -np.inf), False), (left - 3, True),
                            (right + 3, True), (np.nextafter(right + 3, np.inf), False)):
        candidates, _ = find_candidates(pd.DataFrame([passage]), [event],
                                        offset_tolerance_s=5, time_origin=clock,
                                        time_tolerance_s=3)
        assert bool(candidates) is expected


def test_real_two_pass_pair_survives_inclusive_fixed_clock_boundary():
    fixture = json.loads((Path(__file__).parent / 'data' / 'reference-cpa-real.json').read_text())
    events = fixture['events'][:2]
    passages = [fixture['cpa_rows'][0], fixture['cpa_rows'][27]]
    clock = passages[0]['receive_time'] - events[0]['cpa_receive_s'] - (
        events[0]['quality']['cpa_tolerance_s'] + 2.5)
    candidates, _ = pair_candidates(pd.DataFrame(passages), events, offset_tolerance_s=5,
                                    time_origin=clock, time_tolerance_s=0)
    assert any([p['flight_id'] for p in item['passes']] == ['06a128', 'ac79b1']
               for item in candidates)
