"""Independent four-flyover MP3 fixture with opaque flight IDs and separate truth.

The first two events have distant geometric decoys; later locked timings differ.
The renderer transports emission phase, never calling the inverse search model.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
from pyproj import Transformer
import soundfile as sf


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def generate(output, seed=502013):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    inputs, hidden = output / "inputs", output / "truth"
    inputs.mkdir()
    hidden.mkdir()
    rng = np.random.default_rng(seed)
    sr, duration, epoch = 8000, 520, 1790000000.0
    time = np.arange(duration * sr) / sr
    audio = rng.normal(0, 0.02, len(time))
    truth = {"location": [36.11951, -96.32709], "elev_m": 122., "recording_start_time_s": epoch,
             "location_accuracy_eligible": True, "flight_ids": [], "events": []}
    earth = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
    observer = np.array(earth.transform(truth["location"][1], truth["location"][0], truth["elev_m"]))
    rows = []
    for region, (lat0, lon0) in enumerate([truth["location"], [33.1, -87.2], [44.3, -112.1]]):
        inverse = Transformer.from_crs(f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m", "EPSG:4326", always_xy=True)
        for index, center in enumerate([65., 185., 305., 425.]):
            identity = hashlib.sha256(f"{seed}:{region}:{index}".encode()).hexdigest()[:16]
            heading = [0., np.pi/2, np.pi/3, 2*np.pi/3][index]

            def position(t):
                speed = [75., 82., 88., 70.][index] * (1.12 if region and index >= 2 else 1.)
                along = speed*t + 0.035*t*t
                cross = 1000 + 140*index + 0.045*t*t + (450 if region and index >= 2 else 0)
                return (along*np.cos(heading)-cross*np.sin(heading),
                        along*np.sin(heading)+cross*np.cos(heading), 900+180*index+0.5*t)

            # All regions participate in input data. No target-flight allowlist.
            shift = (12. if index == 2 else 25.) if region and index >= 2 else 0.
            relative = np.arange(-75., 76.)
            x, y, h = position(relative)
            lon, lat = inverse.transform(x, y)
            for j in range(len(relative)):
                rows.append({"flight_id": identity, "time_s": epoch+center+shift+relative[j],
                             "lat": lat[j], "lon": lon[j], "alt_m": h[j]+truth["elev_m"],
                             "altitude_basis": "synthetic_geometric_wgs84", "typecode": "C172"})
            if region:
                continue
            emission = np.arange(-40*sr, 40*sr) / sr
            x, y, h = position(emission)
            lon, lat = inverse.transform(x, y)
            xyz = np.column_stack(earth.transform(lon, lat, h+truth["elev_m"]))
            distance = np.linalg.norm(xyz-observer, axis=1)
            arrival = center+emission+distance/343.
            frequency = [122., 145., 174., 101.][index]
            envelope = np.hanning(len(emission)) * np.minimum(1., 1600/distance)
            source = 0.22*envelope*(np.sin(2*np.pi*frequency*emission)+0.45*np.sin(4*np.pi*frequency*emission+0.3))
            audio += np.interp(time, arrival, source, left=0, right=0)
            truth["flight_ids"].append(identity)
            truth["events"].append({"start_s": float(arrival[0]), "end_s": float(arrival[-1])})
    sf.write(inputs / "recording.wav", audio, sr, subtype="PCM_16")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(inputs / "recording.wav"),
                    "-map_metadata", "-1", "-codec:a", "libmp3lame", "-b:a", "96k", str(inputs / "recording.mp3")], check=True)
    pd.DataFrame(rows).to_csv(inputs / "flights.csv", index=False)
    start = datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    dump(inputs / "request.json", {"schema_version": 1, "audio_path": "recording.mp3", "search": {"coverage": "conus"},
          "time_window": {"start_utc": start, "end_utc": start, "source": "user", "source_detail": "Predeclared synthetic renderer epoch."}})
    dump(inputs / "manifest.json", {"schema_version": 1, "cases": [{"case_id": "multievent-001", "split": "development",
          "scope": "automatic_multievent_synthetic", "request": "request.json",
          "audio_sha256": hashlib.sha256((inputs / "recording.mp3").read_bytes()).hexdigest(), "duration_s": duration}]})
    dump(hidden / "labels.json", {"multievent-001": truth})
    dump(output / "provenance.json", {"generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "seed": seed, "sample_rate_hz": sr, "duration_s": duration,
          "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs.iterdir())},
          "scope": "Four independent synthetic events, three-region toy flight universe; no real accuracy claim.",
          "license": "Generated audio contains no third-party media; repository has no declared license."})
    return inputs / "manifest.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=502013)
    args = parser.parse_args()
    print(generate(args.output, args.seed))
