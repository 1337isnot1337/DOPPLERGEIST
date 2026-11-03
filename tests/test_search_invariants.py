"""Selected events and unselected traffic have different silence semantics."""

import pandas as pd
import pytest

from dopplergeist.search import pair_candidates


EPOCH = 1_790_000_000.0


def _pass(flight_id, receive_s, distance_m=2000.0):
    receive_time = EPOCH + receive_s
    return {
        "point_id": 0,
        "flight_id": flight_id,
        "emission_time": receive_time - distance_m / 343.0,
        "receive_time": receive_time,
        "distance_m": distance_m,
        "speed_mps": 80.0,
    }


def _three_event_case(flight_ids=("a", "b", "c")):
    # One shared recording clock aligns every observed event with its pass.
    events = [
        {
            "cpa_receive_s": when,
            "speed_range_mps": [60.0, 100.0],
            "slant_range_m": [1000.0, 3000.0],
        }
        for when in (50.0, 550.0, 1050.0)
    ]
    rows = [
        _pass(flight_id, when)
        for flight_id, when in zip(flight_ids, (100.0, 600.0, 1100.0))
    ]
    return rows, events


@pytest.mark.parametrize(
    "flight_ids", [("a", "b", "c"), ("a", "a", "a")],
    ids=["distinct-aircraft", "repeated-aircraft"],
)
def test_selected_middle_pass_is_not_an_unobserved_flyover(flight_ids):
    rows, events = _three_event_case(flight_ids)
    table = pd.DataFrame(rows)
    without_silence, _ = pair_candidates(table, events)
    assert len(without_silence) == 1

    candidates, counts = pair_candidates(
        table, events, silence={"edge_margin_s": 60.0},
    )

    assert candidates == without_silence
    assert counts["pairs_before_silence"] == 1
    assert counts["silence_rejected"] == 0
    assert [p["flight_id"] for p in candidates[0]["passes"]] == list(flight_ids)


@pytest.mark.parametrize("extra_flight_id", ["extra", "a"])
def test_unselected_close_pass_still_violates_silence(extra_flight_id):
    rows, events = _three_event_case()
    # The second case is a later, unselected pass by the first selected aircraft.
    # Excluding the selected aircraft's entire flight ID would hide this pass.
    rows.append(_pass(extra_flight_id, 850.0, distance_m=1800.0))
    table = pd.DataFrame(rows)
    without_silence, _ = pair_candidates(table, events)
    assert len(without_silence) == 1

    candidates, counts = pair_candidates(
        table, events, silence={"edge_margin_s": 60.0},
    )

    assert candidates == []
    assert counts["pairs_before_silence"] == 1
    assert counts["silence_rejected"] == 1


def test_unselected_distant_pass_does_not_trigger_silence_heuristic():
    rows, events = _three_event_case()
    rows.append(_pass("extra", 850.0, distance_m=2400.0))
    table = pd.DataFrame(rows)
    without_silence, _ = pair_candidates(table, events)
    assert len(without_silence) == 1

    candidates, counts = pair_candidates(
        table, events, silence={"edge_margin_s": 60.0},
    )

    assert candidates == without_silence
    assert counts["silence_rejected"] == 0
