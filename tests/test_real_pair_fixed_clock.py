"""Fixed-clock pair regression from observed flights and real audio proposals."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from dopplergeist.search import pair_candidates


def test_real_pair_keeps_inclusive_clock_boundaries():
    data = json.loads((Path(__file__).parent / "data" / "reference-cpa-real.json").read_text())
    events = data["events"][:2]
    passages = [data["cpa_rows"][0], data["cpa_rows"][27]]
    centers = [row["receive_time"] - event["cpa_receive_s"]
               for row, event in zip(passages, events)]
    tolerances = [event["quality"]["cpa_tolerance_s"] + 2.5 for event in events]
    left = max(center - tolerance for center, tolerance in zip(centers, tolerances))
    right = min(center + tolerance for center, tolerance in zip(centers, tolerances))
    assert left < right
    table = pd.DataFrame(passages)
    for clock, expected in ((np.nextafter(left, -np.inf), False), (left, True),
                            (np.nextafter(left, np.inf), True), (np.nextafter(right, -np.inf), True),
                            (right, True), (np.nextafter(right, np.inf), False)):
        candidates, _ = pair_candidates(table, events, offset_tolerance_s=5,
                                        time_origin=clock, time_tolerance_s=0)
        assert bool(candidates) is expected
    for clock, expected in ((np.nextafter(left - 3, -np.inf), False), (left - 3, True),
                            (right + 3, True), (np.nextafter(right + 3, np.inf), False)):
        candidates, _ = pair_candidates(table, events, offset_tolerance_s=5,
                                        time_origin=clock, time_tolerance_s=3)
        assert bool(candidates) is expected
