"""Profile a completed regional development search without reading location truth."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from dopplergeist.audio import Spectrum
from dopplergeist.matching import profile_candidate
from dopplergeist.terrain import Terrain
from dopplergeist.tracks import load_tracks, unix_time


class CachedRaster:
    """Regional replay only: cache one declared raster's unchanged sample grid."""
    def __init__(self, raster):
        self.raster = raster
        self.data = raster.read(1, masked=True)

    def __getattr__(self, name):
        return getattr(self.raster, name)

    def read(self, index, masked=True):
        return self.data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Completed search directory")
    parser.add_argument("--output", type=Path, required=True, help="New profile output directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = json.loads((args.run/"report.json").read_text())
    config, events = report["config"], report["measured_events"]
    measurements = []
    hashes = {}
    for i in range(len(events)):
        path = args.run/f"event-{i+1}.npz"
        with path.open("rb") as stream:
            hashes[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
        with np.load(path) as data:
            spec = Spectrum(*(data[name] for name in ("time", "frequency", "db", "contrast")))
            measurements.append((spec, data["ridge"], data["weight"], {}))
    tracks = []
    for imported in report["imports"]:
        loaded, _ = load_tracks(imported["path"], max_gap_s=config.get("max_track_gap_s", 30))
        tracks.extend(loaded)
    ground = config["terrain"]
    terrain_hashes = {}
    for filename in ground.get("rasters", [])+[ground["geoid_raster"]] if ground.get("geoid_raster") else ground.get("rasters", []):
        with Path(filename).open("rb") as stream:
            terrain_hashes[filename] = hashlib.file_digest(stream, "sha256").hexdigest()
    terrain = Terrain(ground.get("rasters", []), ground.get("constant_m"), ground.get("geoid_raster"))
    terrain.rasters = [CachedRaster(r) for r in terrain.rasters]
    if terrain.geoid:
        terrain.geoid.rasters = [CachedRaster(r) for r in terrain.geoid.rasters]
    fixed = unix_time(config["recording_start_utc"]) if config.get("recording_start_utc") is not None else None
    window = None if fixed is None else (fixed, fixed)
    result = profile_candidate(report["best"], {t.id:t for t in tracks}, events, measurements,
                               terrain, recording_start_window_s=window)
    root = Path(__file__).resolve().parents[1]
    receipt = {"scope": "manually configured regional development sensitivity; no independent/national acceptance claim",
               "ground_truth_read": False, "source_search": str(args.run.resolve()),
               "source_search_implementation_sha256": report["implementation_sha256"],
               "profile_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
               "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "terrain_sha256": terrain_hashes,
               "measurement_sha256": hashes, "result": result}
    (args.output/"profile.json").write_text(json.dumps(receipt, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"best": [result["lat"], result["lon"]],
                      "sensitivity_radius_m": result["sensitivity"]["radius_m"],
                      "complete": result["sensitivity"]["complete"],
                      "boundary_limited": result["sensitivity"]["boundary_limited"]}))


if __name__ == "__main__":
    main()
