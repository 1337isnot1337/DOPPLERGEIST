"""Check the independent renderer against closed-form constant-velocity sound."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest


spec = importlib.util.spec_from_file_location("multi_event_renderer", Path(__file__).parents[1] / "scripts/make_multi_event_case.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


@pytest.mark.parametrize("radial_velocity", [-80.0, 0.0, 80.0])
def test_emission_transport_frequency_and_travel_delay(radial_velocity):
    rate, frequency, distance = 16000, 230.0, 2000.0
    emission = np.arange(-2 * rate, 2 * rate) / rate
    receive = np.arange(12 * rate) / rate
    waveform = renderer.transport(emission, distance + radial_velocity * emission,
                                  np.sin(2 * np.pi * frequency * emission), receive)
    keep = (receive > distance / 343 - 0.5) & (receive < distance / 343 + 0.5)
    t, y = receive[keep], waveform[keep]
    crossing = np.flatnonzero((y[:-1] < 0) & (y[1:] >= 0))
    zeros = t[crossing] - y[crossing] * (t[1] - t[0]) / (y[crossing + 1] - y[crossing])
    measured = (len(zeros) - 1) / (zeros[-1] - zeros[0])
    assert measured == pytest.approx(frequency * 343 / (343 + radial_velocity), abs=0.02)
    assert np.all(waveform[receive < emission[0] + (distance + radial_velocity * emission[0]) / 343] == 0)
    nearest_zero = zeros[np.argmin(abs(zeros - distance / 343))]
    assert nearest_zero == pytest.approx(distance / 343, abs=1 / rate)


def test_nonmonotonic_arrivals_are_rejected():
    with pytest.raises(ValueError, match="increasing"):
        renderer.transport(np.array([0.0, 1.0]), np.array([1000.0, 0.0]),
                           np.array([0.0, 1.0]), np.array([0.0]))
