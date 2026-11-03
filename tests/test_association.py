from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from dopplergeist.matching import RidgeTimes, association_candidates, refine_candidate
from dopplergeist.search import score_candidate


class Flyover:
    def __init__(self, center):
        self.center = center

    def acoustic(self, t, observer, c):
        t = np.asarray(t)
        return 1.1 - 0.25*np.tanh((t-self.center)/8), t-5, np.full_like(t, 1700)


def case():
    centers = [30, 500, 950]
    tracks, events, measurements, rows = {}, [], [], []
    for i, center in enumerate(centers):
        identity = f"track-{i}"
        tracks[identity] = Flyover(center)
        times = np.arange(center-25, center+25, 0.5)
        frequency = 120*tracks[identity].acoustic(times, None, 343)[0]
        if i == 1:
            frequency = np.random.default_rng(12).uniform(90, 160, len(times))
        events.append(dict(event_id=f"event-{i}", cpa_receive_s=center,
                           f0_range_hz=[119, 121], speed_range_mps=[60, 100], slant_range_m=[500, 3000]))
        measurements.append((RidgeTimes(times), frequency, np.ones(len(times)), {}))
        rows.append(dict(point_id=0, flight_id=identity, receive_time=center, emission_time=center-5,
                         speed_mps=80, distance_m=1700))
    return pd.DataFrame(rows), tracks, events, measurements


def test_unmatched_false_proposal_does_not_suppress_two_locked_real_events():
    table, tracks, events, measurements = case()
    candidates, counts = association_candidates(table, events, time_origin=0)
    point = SimpleNamespace(point_id=0, lat=40, lon=-100, elev_m=100, x=0, y=0)
    ranked = [score_candidate(c, point, tracks, events, measurements, mode="robust_ridge",
                              time_origin=0, time_sweep_s=0) for c in candidates]
    winner = max(ranked, key=lambda row: row["score"])
    assert winner["event_indices"] == [0, 2]
    assert winner["unmatched_event_ids"] == ["event-1"]
    assert winner["flight_ids"] == ["track-0", "track-2"]
    assert winner["recording_start_time_s"] == 0
    assert abs(winner["score"]-2) < 1e-7
    assert winner["score_kind"] == "matched_group_support_minus_normalized_residual"
    assert counts["unmatched_proposals_allowed"]
    assert counts["max_matched_events"] == 3
    assert not np.isfinite(next(r for r in ranked if r["event_indices"] == [0, 1, 2])["score"])
    terrain = SimpleNamespace(sample=lambda lat, lon: np.array(100.0))
    refined = refine_candidate(winner, tracks, events, measurements, terrain,
                               recording_start_window_s=(0.0, 0.0), altitude_offsets_m=(0.0,))
    assert refined["event_indices"] == [0, 2]
    assert refined["unmatched_event_ids"] == ["event-1"]
    assert abs(refined["score"]-winner["score"]) < 1e-7
    assert refined["score_kind"] == winner["score_kind"]


def test_association_budget_and_noise_only_hypotheses_fail_explicitly():
    table, tracks, events, measurements = case()
    with pytest.raises(ValueError, match="budget exceeded"):
        association_candidates(table, events, time_origin=0, max_candidates=1)
    candidates, _ = association_candidates(table, events[1:2], time_origin=0)
    point = SimpleNamespace(point_id=0, lat=40, lon=-100, elev_m=100, x=0, y=0)
    rows = [score_candidate(c, point, tracks, events[1:2], measurements[1:2],
                            mode="robust_ridge", time_origin=0, time_sweep_s=0) for c in candidates]
    assert rows and not any(np.isfinite(row["score"]) for row in rows)


def test_repeated_passes_remain_distinct_and_one_pass_cannot_explain_two_events():
    table, tracks, events, measurements = case()
    table["flight_id"] = "one-aircraft"
    candidates, _ = association_candidates(table, events, time_origin=0)
    triple = next(c for c in candidates if c["event_indices"] == [0, 1, 2])
    assert len({p["emission_time"] for p in triple["passes"]}) == 3
    overlapping = [dict(events[0], quality={"cpa_tolerance_s": 1000}),
                   dict(events[1], quality={"cpa_tolerance_s": 1000})]
    candidates, _ = association_candidates(table.iloc[:1], overlapping, min_events=2)
    assert not candidates
