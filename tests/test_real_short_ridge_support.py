"""Real discovery/measurement boundary, without generated audio or trajectories."""
import json
from pathlib import Path

import pytest

from dopplergeist.automatic import UnreconciledDiscovery, _search
from dopplergeist.contracts import validate_event
from dopplergeist.matching import InsufficientRidgeSamples, prepare_events


FIXTURES = Path(__file__).parent / "fixtures"


def recorded(name):
    return json.loads((FIXTURES / name).read_text())["events"]


def test_valid_seven_sample_discovery_is_unsupported_before_acquisition(tmp_path):
    events = recorded("real_livermore_short_ridge.json")
    assert len(events) == 1 and len(events[0]["ridge"]) == 7
    for event in events:
        validate_event(event)
    # Preparation precedes clock/data use. Reaching those stages would fail
    # this control; no invented recording, clock, flights or terrain are supplied.
    with pytest.raises(UnreconciledDiscovery, match="samples"):
        _search({}, None, events, tmp_path, {}, None)
    assert list(tmp_path.iterdir()) == []


def test_supported_recorded_group_keeps_its_measurements():
    events = recorded("real_livermore_supported_ridge.json")
    for event in events:
        validate_event(event)
    settings, measured = prepare_events(events)
    assert len(settings) == len(measured) == 1
    assert settings[0]["event_ids"] == [event["event_id"] for event in events]
    assert len(measured[0][0].time) == sum(len(event["ridge"]) for event in events)


def test_below_contract_minimum_stays_an_invalid_input(tmp_path):
    events = recorded("real_livermore_short_ridge.json")
    events[0]["ridge"] = events[0]["ridge"][:2]  # Two actual observations, not generated points.
    with pytest.raises(ValueError, match="at least three points") as error:
        _search({}, None, events, tmp_path, {}, None)
    assert not isinstance(error.value, (UnreconciledDiscovery, InsufficientRidgeSamples))


@pytest.mark.parametrize("count", [9, 10])
def test_sample_minimum_is_preserved_on_recorded_observations(count):
    events = recorded("real_livermore_supported_ridge.json")
    assert len(events) == 1
    events[0]["ridge"] = events[0]["ridge"][:count]
    validate_event(events[0])
    if count == 9:
        with pytest.raises(InsufficientRidgeSamples, match="9 ridge samples"):
            prepare_events(events)
    else:
        settings, measured = prepare_events(events)
        assert len(settings) == len(measured) == 1
        assert len(measured[0][0].time) == 10
