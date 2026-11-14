"""Compare bounded verification with the eager reference on actual recorded PCM."""
import gzip
import json
from pathlib import Path

import numpy as np
import pytest
from scipy import signal

from dopplergeist import advanced_discovery
from dopplergeist.discovery import discover_events
from dopplergeist.intake import IntakeRecording, intake_recording


FIXTURES = Path(__file__).parent / 'fixtures'


class EagerSpectra:
    """The previous whole-recording SciPy calculation, kept only as a reference."""

    def __init__(self, recording):
        samples = np.memmap(recording.samples_path, dtype='<f4', mode='r')
        rate = recording.metadata['sample_rate_hz']
        f, self.time_s, power = signal.spectrogram(samples, fs=rate,
            nperseg=round(rate * 0.5), noverlap=0, window='hann', scaling='density')
        keep = (f >= 10) & (f <= min(8200.0, recording.source_nyquist_hz))
        self.frequency_hz = f[keep]
        self.db = 10 * np.log10(np.maximum(power[keep], 1e-30))

    def column(self, index):
        return self.db[:, index]


@pytest.fixture(scope='module', params=['native', 'lowrate'])
def recorded_source(request, tmp_path_factory):
    root = tmp_path_factory.mktemp('actual-verification')
    if request.param == 'native':
        source = FIXTURES / 'aerosonic-propeller-7c293d-22s.flac'
    else:
        source = root / 'actual-lowrate.wav'
        source.write_bytes(gzip.decompress((FIXTURES / 'real_lowrate_piston_1000hz.wav.gz').read_bytes()))
    return root, source


@pytest.mark.parametrize('rate', [4000, 24000])
@pytest.mark.parametrize('block_windows', [1, 5])
def test_all_recorded_columns_are_exact_through_cache_eviction(recorded_source, rate, block_windows):
    root, source = recorded_source
    recording = intake_recording(source, root / f'spectra-{rate}-{block_windows}', sample_rate_hz=rate)
    # Drop only the final seventeen real samples to exercise an incomplete window.
    # No padding, joins, tones, trajectories or clocks are generated.
    partial = recording.samples_path.with_name('actual-tail-excerpt.f32')
    partial.write_bytes(recording.samples_path.read_bytes()[:-17 * 4])
    recording = IntakeRecording(partial, recording.metadata, recording.diagnostics, source)
    expected = EagerSpectra(recording)
    actual = advanced_discovery._VerificationSpectra(recording, block_windows=block_windows)
    np.testing.assert_array_equal(actual.frequency_hz, expected.frequency_hz)
    np.testing.assert_array_equal(actual.time_s, expected.time_s)
    assert len(actual.time_s) > 4
    # Both directions revisit evicted blocks and cover the final partial block.
    for index in [*range(len(actual.time_s)), *reversed(range(len(actual.time_s)))]:
        np.testing.assert_array_equal(actual.column(index), expected.column(index))
        assert len(actual._cache) <= 4
        assert sum(value.nbytes for value in actual._cache.values()) <= (
            4 * block_windows * len(actual.frequency_hz) * np.dtype('float32').itemsize)


@pytest.fixture(scope='module')
def recorded_tracks(tmp_path_factory):
    root = tmp_path_factory.mktemp('actual-verified-tracks')
    source = root / 'actual-lowrate.wav'
    source.write_bytes(gzip.decompress((FIXTURES / 'real_lowrate_piston_1000hz.wav.gz').read_bytes()))
    recording = intake_recording(source, root / 'scan-intake')
    events = discover_events(recording, output_dir=root / 'scan',
        plot_summary=False, plot_event_details=False, event_audio=False)
    assert events
    high = root / 'scan/intake_high'
    return IntakeRecording(high / 'recording.f32',
        json.loads((high / 'recording.json').read_text()),
        json.loads((high / 'intake.json').read_text()), source), events


@pytest.mark.parametrize('variant', ['pass_v25', 'consensus'])
def test_complete_recorded_verification_is_exact(recorded_tracks, variant, monkeypatch):
    recording, events = recorded_tracks
    actual = advanced_discovery.verify_tracks(recording, events, variant)
    monkeypatch.setattr(advanced_discovery, '_VerificationSpectra', EagerSpectra)
    expected = advanced_discovery.verify_tracks(recording, events, variant)
    assert actual == expected
