"""Investigate ambiguity using existing public recordings, not generated audio."""
import copy
import json
import os
from pathlib import Path

import pytest

from dopplergeist.confidence import _possible_harmonic_overlap
from dopplergeist.contracts import validate_event


def test_real_overlapping_ridges_have_unresolved_harmonic_ambiguity():
    source = os.environ.get("DOPPLERGEIST_REAL_HARMONIC_SCAN")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_HARMONIC_SCAN to the saved real scan JSON")
    events = [validate_event(event) for event in json.loads(Path(source).read_text())["events"]]
    assert len(events) == 2 and events[0]["harmonic_group_id"] != events[1]["harmonic_group_id"]
    flag = _possible_harmonic_overlap(events)
    assert flag and set(flag["event_ids"]) == {event["event_id"] for event in events}
    assert flag["harmonic_ratio"] == 1.5 and flag["aligned_samples"] >= 10
    assert flag["residual_q90_hz"] <= flag["heuristic_tolerance_hz"]
    assert _possible_harmonic_overlap(events[:1]) is None
    # Metadata-only relabeling checks that existing harmonic groups are not
    # compared against themselves; the recorded ridge samples are untouched.
    grouped = copy.deepcopy(events)
    grouped[1]["harmonic_group_id"] = grouped[0]["harmonic_group_id"]
    assert _possible_harmonic_overlap(grouped) is None


def test_real_unflagged_group_pair_is_not_automatically_rejected():
    source = os.environ.get("DOPPLERGEIST_REAL_HARMONIC_CONTROL")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_HARMONIC_CONTROL to a saved real scan JSON")
    events = [validate_event(event) for event in json.loads(Path(source).read_text())["events"]]
    assert len({event["harmonic_group_id"] for event in events}) >= 2
    # Absence of a flag is not proof that these are independent aircraft.
    assert _possible_harmonic_overlap(events) is None
