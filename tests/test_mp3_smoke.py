"""Small actual-codec smoke check; no network or large release data."""
import subprocess

import numpy as np
import soundfile as sf

from aircraft_geoloc.audio import decode


def test_mp3_decode_preserves_timing_and_tone(tmp_path):
    sample_rate = 16000
    time = np.arange(sample_rate * 3) / sample_rate
    original = 0.2 * np.sin(2 * np.pi * 440 * time)
    wav, mp3 = tmp_path / "tone.wav", tmp_path / "tone.mp3"
    sf.write(wav, original, sample_rate)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(wav),
                    "-codec:a", "libmp3lame", "-b:a", "64k", str(mp3)], check=True)
    samples, rate = decode(mp3, sample_rate=4000)
    assert rate == 4000
    assert abs(len(samples) / rate - 3) < 0.025
    peak = np.fft.rfftfreq(len(samples), 1 / rate)[np.argmax(abs(np.fft.rfft(samples)))]
    assert abs(peak - 440) < 1
    assert np.max(np.abs(samples)) > 0.1
