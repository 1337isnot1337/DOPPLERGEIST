"""Splitting the candidate list across workers must not change the ranking.

`pipeline.run` scores candidates in blocks, optionally in forked workers. Candidates are independent,
so the only thing a block boundary may touch is ordering, and the assembly step reproduces candidate
order, which is what the ranked list (and its tie handling) depends on.
"""
from types import SimpleNamespace

import numpy as np

from dopplergeist.audio import Spectrum
from dopplergeist.pipeline import merge_blocks, score_block, score_chunks


class Flyover:
    """A tone that sweeps as the aircraft passes, in the shape score_candidate expects."""

    def __init__(self, center):
        self.center = center

    def acoustic(self, t, observer, c):
        factor = 1.1 - 0.25 * np.tanh((t - self.center) / 8)
        return factor, np.asarray(t), np.ones_like(t)


def case(points, candidates, center=30.0):
    t = np.arange(center - 25, center + 25, 0.5)
    spec = Spectrum(t, np.arange(80, 161), np.zeros((81, len(t))), np.zeros((81, len(t))))
    ridge = 120 * Flyover(center).acoustic(t, None, 343)[0]
    measurements = [(spec, ridge, np.ones(len(t)), {})]
    events = [{"cpa_receive_s": center, "f0_range_hz": [119.9, 120.1]}]
    lookup = {p.point_id: p for p in points}
    # Tracks centred on the event score near zero; the offset one cannot fit the same clock.
    track_lookup = {"a": Flyover(center), "b": Flyover(center + 7.5)}
    parameters = dict(mode="ridge", time_origin=0, time_sweep_s=10, time_step_s=0.5)
    state = dict(lookup=lookup, track_lookup=track_lookup, events=events,
                 measurements=measurements, parameters=parameters, origin=0)
    return candidates, state


def points_and_candidates(count=6):
    points = [SimpleNamespace(point_id=i, lat=40 + 0.01 * i, lon=-100, elev_m=0, x=0, y=0)
              for i in range(count)]
    candidates = []
    for i in range(count):
        for flight in ("a", "b"):
            candidates.append({"point_id": i,
                               "passes": [{"flight_id": flight, "receive_time": 30.0,
                                           "emission_time": 30.0 + 0.01 * i}]})
    return points, candidates


def ranked_signature(result):
    ranked, unknown, reported, unreported = result
    return ([(row["score"], row.get("pass_emission_times_s")) for row in ranked],
            [(entry["point_id"], entry["flight_ids"]) for entry in unknown],
            dict(reported), unreported)


def test_block_sizes_and_workers_preserve_the_ranking():
    points, candidates = points_and_candidates()
    candidates, state = case(points, candidates)

    serial = score_block(candidates, state["lookup"], state["track_lookup"], state["events"],
                         state["measurements"], state["parameters"], state["origin"])
    expected = ranked_signature(serial)
    assert len(serial[0]) == len(candidates), "every candidate should produce a finite score"

    for chunks in (1, 2, 5, len(candidates)):
        for workers in (1, 2, 4):
            got = ranked_signature(merge_blocks(
                score_chunks(candidates, chunks, workers, state)))
            assert got == expected, f"chunks={chunks} workers={workers} changed the ranking"


def test_worker_pool_matches_serial_scores_exactly():
    points, candidates = points_and_candidates(count=9)
    candidates, state = case(points, candidates)
    serial = merge_blocks(score_chunks(candidates, len(candidates), 1, state))
    parallel = merge_blocks(score_chunks(candidates, 2, 4, state))
    assert [row["score"] for row in parallel[0]] == [row["score"] for row in serial[0]]
    assert [row["point_id"] for row in parallel[0]] == [row["point_id"] for row in serial[0]]


def test_ordering_inside_a_block_is_preserved_across_blocks():
    points, candidates = points_and_candidates(count=4)
    candidates, state = case(points, candidates)
    # Equal scores must keep candidate order regardless of where the block boundary falls.
    blocks = merge_blocks(score_chunks(candidates, 1, 3, state))[0]
    single = merge_blocks(score_chunks(candidates, len(candidates), 1, state))[0]
    assert [(row["score"], row["point_id"]) for row in blocks] == \
           [(row["score"], row["point_id"]) for row in single]
