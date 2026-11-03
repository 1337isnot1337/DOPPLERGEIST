"""Small deterministic media for real upload/UI checks, without location truth."""
import argparse
import json
from pathlib import Path
import subprocess

import numpy as np
import soundfile as sf


def make(output):
    output.mkdir(parents=True, exist_ok=False)
    sample_rate = 8000
    t = np.arange(sample_rate * 40) / sample_rate
    for name, frequency in (("stationary", np.full_like(t, 200)), ("moving", 220 - t)):
        wave = (.3 * np.sin(2 * np.pi * 200 * t) if name == "stationary" else
                .3 * np.sin(2 * np.pi * np.cumsum(frequency) / sample_rate))
        wave += np.random.default_rng(913).normal(0, .002, len(t))
        source = output / (name + ".wav")
        sf.write(source, wave, sample_rate)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(source),
                        "-c:a", "libmp3lame", str(output / (name + ".mp3"))], check=True)
    (output / "invalid.mp3").write_bytes(b"This is deliberately invalid encoded audio for a decoding control.")
    request = {"schema_version": 1, "search": {"coverage": "conus"}}
    (output / "missing-time.json").write_text(json.dumps(request, indent=2) + "\n")
    request["time_window"] = {"start_utc": "2026-09-21T13:13:20Z", "end_utc": "2026-09-21T13:13:20Z",
                              "source": "user", "source_detail": "Synthetic acoustic control; no real recording-clock or location claim."}
    (output / "timed.json").write_text(json.dumps(request, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    make(parser.parse_args().output)
