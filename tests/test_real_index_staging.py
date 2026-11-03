"""Check index staging against archived real flight observations."""
import json
from pathlib import Path

import pandas as pd

from dopplergeist.data_access import _staging_rows


def test_staging_preserves_real_observation_values():
    source = Path(__file__).resolve().parents[1] / "research/trajectory-motion/frozen/canonical-observations.json"
    frame = pd.DataFrame(json.loads(source.read_text()))
    expected = json.loads(frame.to_json(orient="records", double_precision=15))
    rows = list(_staging_rows(frame))
    assert len(rows) == len(expected) > 0
    for record, (flight, timestamp, payload) in zip(expected, rows):
        assert flight == str(record["flight_id"])
        assert timestamp == record["time_s"]
        assert json.loads(payload) == record
    assert list(_staging_rows(frame.iloc[:0])) == []
