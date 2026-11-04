"""Software regression on measured public Michigan recording traces only."""
import json
from pathlib import Path

from dopplergeist.coherent_discovery import events_from_coherent_traces
from dopplergeist.contracts import validate_event
from dopplergeist.matching import prepare_events


def test_real_slow_traces_survive_without_geometry_or_kind_gates():
    fixture = Path(__file__).parent / "fixtures/real_coherent_michigan.json"
    rows = json.loads(fixture.read_text())["traces"]
    events = events_from_coherent_traces(rows)
    assert len(events) == 2
    assert sorted(len(event["ridge"]) for event in events) == [58, 66]
    assert all(validate_event(event) == event for event in events)
    assert all(row["proposal"]["v"] < 30 for row in rows[:2])
    observed = {(p["time_s"], p["frequency_hz"]) for row in rows for p in row["ridge_points"]}
    assert all((p["time_s"], p["frequency_hz"]) in observed for e in events for p in e["ridge"])
    settings, measurements = prepare_events(events, c=333.3)
    assert sum(len(measurement[1]) for measurement in measurements) == 124
    assert all(event["speed_range_mps"] == [0., 333.3] for event in settings)
    assert all(event["slant_range_m"] == [0., 20000.] for event in settings)


def test_real_noisier_trace_fails_reference_quality_gate():
    fixture = Path(__file__).parent / "fixtures/real_coherent_michigan.json"
    rows = json.loads(fixture.read_text())["traces"]
    # This actual 40-point trace fails the existing 1% fit criterion; the two
    # slower traces above pass. No aircraft-type conclusion follows either way.
    assert len(rows[2]["ridge_points"]) == 40
    assert rows[2]["proposal"]["rms"] / rows[2]["proposal"]["f_main"] > .01
    assert events_from_coherent_traces(rows[2:]) == []
