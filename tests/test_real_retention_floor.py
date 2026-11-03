"""Retention-cutoff checks replaying actual fitted modes, not generated flyovers."""
import json
from pathlib import Path

from dopplergeist.tiled_search import _RetainedScoreFloor, _retained_score_floor


def test_real_modes_keep_the_kth_distinct_score_under_reordering_and_repetition():
    rows = json.loads((Path(__file__).parent / 'data/reference-retention-real.json').read_text())['rows']
    for k in (1, 5, 100):
        for sequence in (rows, list(reversed(rows)), rows * 3):
            floor = _RetainedScoreFloor(k)
            seen = {}
            for row in sequence:
                floor.observe(dict(row))
                seen[row['mode_id']] = max(row['score'], seen.get(row['mode_id'], -float('inf')))
                expected = sorted(seen.values(), reverse=True)[k-1] if len(seen) >= k else None
                assert floor.value == expected
                assert len(floor.scores) <= k


def test_global_floor_requires_the_retained_mode_count():
    rows = json.loads((Path(__file__).parent / 'data/reference-retention-real.json').read_text())['rows']
    assert _retained_score_floor(rows, len(rows)) == min(row['score'] for row in rows)
    assert _retained_score_floor(rows, 100) is None
    global_floor = _retained_score_floor(rows, len(rows))
    local = _RetainedScoreFloor(len(rows), global_floor)
    for row in rows:
        local.observe(dict(row))
        assert local.value >= global_floor
