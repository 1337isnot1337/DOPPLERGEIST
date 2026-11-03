"""Compare audio performance against another checkout on a real recording.

The full recording is decoded once and both implementations receive identical
samples and discovery settings. All event fields must match exactly. Optional
configured ridge windows check every frequency and weight as well. This measures
runtime and software equivalence, not aircraft identity or localization accuracy.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

import numpy as np

from dopplergeist import audio, discovery
from dopplergeist.intake import intake_recording


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _timed(function):
    wall, cpu = time.perf_counter(), time.process_time()
    result = function()
    return result, {"wall_s": time.perf_counter() - wall,
                    "cpu_s": time.process_time() - cpu}


def _summary(samples):
    result = {name: {"trials": values,
                    "median_wall_s": statistics.median(row["wall_s"] for row in values),
                    "median_cpu_s": statistics.median(row["cpu_s"] for row in values)}
              for name, values in samples.items()}
    result["wall_speedup"] = result["baseline"]["median_wall_s"] / result["current"]["median_wall_s"]
    result["cpu_speedup"] = result["baseline"]["median_cpu_s"] / result["current"]["median_cpu_s"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", help="Actual recorded audio, never a generated fixture")
    parser.add_argument("--baseline", required=True, help="Unmodified baseline checkout")
    parser.add_argument("--output", required=True, help="New output directory")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--diagnostics", action="store_true", help="Include diagnostic JSON/CSV/PNG writes")
    parser.add_argument("--ridge-config", help="Existing real-recording configuration with event windows")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    output, baseline = Path(args.output), Path(args.baseline).resolve()
    baseline_audio = _module(baseline / "src/dopplergeist/audio.py", "dopplergeist._baseline_audio")
    baseline_discovery = _module(baseline / "src/dopplergeist/discovery.py", "dopplergeist._baseline_discovery")
    output.mkdir(parents=True, exist_ok=False)
    recording, intake_time = _timed(lambda: intake_recording(args.audio, output / "intake"))
    implementations = {"baseline": baseline_discovery, "current": discovery}
    samples = {name: [] for name in implementations}
    reference = None
    events = []
    for trial in range(args.repeats):
        order = ("baseline", "current") if trial % 2 == 0 else ("current", "baseline")
        for name in order:
            directory = output / f"{name}-{trial + 1}" if args.diagnostics else None
            events, timing = _timed(lambda: implementations[name].discover_events(
                recording, output_dir=directory))
            payload = json.dumps(events, sort_keys=True, allow_nan=False)
            if reference is None:
                reference = payload
            if payload != reference:
                (output / f"mismatch-{name}-{trial + 1}.json").write_text(payload + "\n")
                raise AssertionError("Full discovery event payload changed")
            samples[name].append(timing)
            print(json.dumps({"stage": "discovery", "implementation": name,
                              "trial": trial + 1, "events": len(events), **timing}), flush=True)
    (output / "events.json").write_text(reference + "\n")
    result = {"source": recording.metadata, "intake": intake_time,
              "baseline_commit": subprocess.check_output(
                  ["git", "-C", str(baseline), "rev-parse", "HEAD"], text=True).strip(),
              "diagnostics_included": args.diagnostics,
              "discovery": {**_summary(samples), "exact_event_payload_match": True,
                            "ridge_count": len(events),
                            "independent_group_count": len({e["harmonic_group_id"] for e in events})},
              "scope": "Real-recording runtime/equivalence only; no aircraft or location validation"}
    if args.ridge_config:
        configured = json.loads(Path(args.ridge_config).read_text())
        result["configured_ridges"] = []
        for index, event in enumerate(configured["events"]):
            data, sr = audio.decode(args.audio, event["start_s"], event["end_s"] - event["start_s"])
            spectrum = audio.spectrogram(data, sr, event["band_hz"], event["start_s"],
                                         event.get("window_s", 2.0), event.get("hop_s", 0.25))
            ridge_samples = {"baseline": [], "current": []}
            reference_ridge = None
            for trial in range(args.repeats):
                order = ("baseline", "current") if trial % 2 == 0 else ("current", "baseline")
                for name in order:
                    implementation = baseline_audio if name == "baseline" else audio
                    ridge, timing = _timed(lambda: implementation.trace_ridge(
                        spectrum, event.get("max_slope_hz_s", 12),
                        max_up_slope=event.get("max_up_slope_hz_s", 1.0)))
                    if reference_ridge is None:
                        reference_ridge = ridge
                    if not all(np.array_equal(before, after) for before, after in zip(reference_ridge, ridge)):
                        raise AssertionError(f"Configured ridge {index + 1} changed")
                    ridge_samples[name].append(timing)
            result["configured_ridges"].append({"event": index + 1,
                "spectrum_shape": list(spectrum.contrast.shape),
                "exact_frequency_and_weight_match": True, **_summary(ridge_samples)})
    (output / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
