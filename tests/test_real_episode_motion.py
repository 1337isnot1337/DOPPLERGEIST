"""Motion metrics on unchanged measured AeroSonicDB child ridges."""
import json
from pathlib import Path

import numpy as np

from dopplergeist.episode_discovery import DiscoverySettings
from dopplergeist.episodes import motion


def test_recorded_child_duration_and_support():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/real_episode_children.json").read_text()
    )
    # Durations are the recorded child observation-cell sums in case-0001.
    # Missing intervals remain excluded; these are not continuous-span lengths.
    expected = {
        "ridge-e89a6abd10d83ec9cd4c": (39.0, 45.5),
        "ridge-9834a3c314c9474690ee": (27.5, 33.0),
        "ridge-41f68eae800cafb36acc": (36.5, 36.5),
        "ridge-af2d2e7c0b20d7fec4c2": (12.5, 17.5),
        "ridge-e4492d9b7e99ae1549c9": (17.0, 18.5),
        "ridge-4b9a927849f08dd061ac": (5.0, 8.5),
    }
    events = {event["event_id"]: event for event in fixture["events"]}
    assert set(events) == set(expected)
    settings = DiscoverySettings()
    for event_id, (observed_s, span_s) in expected.items():
        points = np.array([
            [point["time_s"], point["frequency_hz"], point["weight"]]
            for point in events[event_id]["ridge"]
        ])
        metrics, _ = motion(points, settings)
        assert metrics["observed_duration_s"] == observed_s
        assert metrics["span_s"] == span_s
        assert metrics["support_fraction"] == observed_s / span_s
