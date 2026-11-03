"""Compare discovery diagnostic rendering on an existing real-recording run.

The input directory must contain intake/ and discovery/ from discover_audio.py
or an automatic job. Both implementations render every measured ridge with the
same full spectral normalization. Every PNG pixel must match. This measures
diagnostic rendering only, not discovery or end-to-end localization speed.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

import matplotlib
matplotlib.use("Agg")
from matplotlib.image import imread
import numpy as np

from dopplergeist import discovery
from dopplergeist.intake import IntakeRecording


def _module(checkout):
    name = "dopplergeist._baseline_discovery_plots"
    spec = importlib.util.spec_from_file_location(name, checkout / "src/dopplergeist/discovery.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording_directory", type=Path)
    parser.add_argument("--baseline", type=Path, required=True, help="Unmodified baseline checkout")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    intake = args.recording_directory / "intake"
    metadata = json.loads((intake / "recording.json").read_text())
    diagnostics = json.loads((args.recording_directory / "discovery/discovery.json").read_text())
    if metadata["source_sha256"] != diagnostics["source_sha256"]:
        parser.error("Intake and discovery belong to different source recordings")
    recording = IntakeRecording(intake / "recording.f32", metadata, {})
    settings = discovery.DiscoverySettings(**diagnostics["settings"])
    events = diagnostics["events"]
    if not events:
        parser.error("The real recording contains no event diagnostics to compare")
    group_ids = list(dict.fromkeys(event["harmonic_group_id"] for event in events))
    if len(group_ids) != len(diagnostics["harmonic_ridges"]):
        parser.error("Discovery groups and measured harmonic ridges do not agree")
    groups = {name: [np.asarray(points) for points in rows]
              for name, rows in zip(group_ids, diagnostics["harmonic_ridges"])}
    implementations = {"baseline": _module(args.baseline.resolve()), "current": discovery}
    args.output.mkdir(parents=True, exist_ok=False)
    samples = {name: [] for name in implementations}
    reference_directory = None
    # Load the backend, colormap, and fonts before either timed arm.
    implementations["baseline"]._plot_event(recording, groups[events[0]["harmonic_group_id"]],
        events[0], settings, args.output / "warmup.png")
    for trial in range(args.repeats):
        order = ("baseline", "current") if trial % 2 == 0 else ("current", "baseline")
        for name in order:
            directory = args.output / f"{name}-{trial + 1}"
            directory.mkdir()
            started_wall, started_cpu = time.perf_counter(), time.process_time()
            for event in events:
                implementations[name]._plot_event(recording, groups[event["harmonic_group_id"]],
                    event, settings, directory / f"{event['event_id']}.png")
            timing = {"wall_s": time.perf_counter() - started_wall,
                      "cpu_s": time.process_time() - started_cpu}
            samples[name].append(timing)
            if reference_directory is None:
                reference_directory = directory
            for event in events:
                filename = f"{event['event_id']}.png"
                if not np.array_equal(imread(reference_directory / filename), imread(directory / filename)):
                    raise AssertionError(f"Diagnostic pixels changed: {name}, trial {trial + 1}, {filename}")
            print(json.dumps({"implementation": name, "trial": trial + 1, **timing}), flush=True)
    summary = {name: {"trials": rows,
                     "median_wall_s": statistics.median(row["wall_s"] for row in rows),
                     "median_cpu_s": statistics.median(row["cpu_s"] for row in rows)}
               for name, rows in samples.items()}
    summary.update({"source": metadata, "ridge_count": len(events), "group_count": len(groups),
        "exact_png_pixels": True,
        "wall_speedup": summary["baseline"]["median_wall_s"] / summary["current"]["median_wall_s"],
        "cpu_speedup": summary["baseline"]["median_cpu_s"] / summary["current"]["median_cpu_s"],
        "baseline_commit": subprocess.check_output(
            ["git", "-C", str(args.baseline), "rev-parse", "HEAD"], text=True).strip(),
        "scope": "All event PNGs from real measured ridges; excludes intake, discovery, and equality checks"})
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
