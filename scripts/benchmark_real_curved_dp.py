#!/usr/bin/env python3
"""Check and time the identical curved-path recurrence on public real spectra."""
import argparse
import csv
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy import ndimage, signal

from dopplergeist.advanced_discovery import (
    _curved_forward, _curved_forward_reference, local_median, log_image,
)
from dopplergeist.audio import decode


def prepare(data, output):
    output.mkdir(parents=True, exist_ok=False)
    with (data / "sample_meta.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    first = min(row["filename"] for row in rows if row["subclass"] in {"1", "2"})
    sources = [data / "environment" / f"{index}_AUDIO.wav" for index in range(1, 7)]
    sources.append(data / "audio" / first)
    cases = []
    for source in sources:
        samples, sr = decode(source, duration=120, sample_rate=24000)
        samples = samples.astype(np.float32)  # Match intake_recording.iter_chunks.
        for window, hop in ((0.5, 0.125), (2.0, 0.5)):
            n, step = round(window * sr), round(hop * sr)
            if len(samples) < n:
                raise ValueError("Source is shorter than the declared spectral window")
            f, times, power = signal.spectrogram(samples, fs=sr, nperseg=n, noverlap=n - step,
                                                window="hann", scaling="density")
            keep = (f >= 10) & (f <= 8200)
            f = f[keep]
            db = 10 * np.log10(np.maximum(power[keep], 1e-30))
            local = db - local_median(db)
            for band, (low, high) in enumerate(((20.0, 1600.0), (1600.0, 8000.0))):
                if band == 1 and window != 0.5:
                    continue
                bins = 576 if band else 144
                band_local = (db - ndimage.gaussian_filter1d(db, 100.0 / (f[1] - f[0]),
                                                            axis=0, mode="nearest")) if band else local
                _, image = log_image(f, band_local, low, high, bins_per_octave=bins)
                name = f"{len(cases):02d}-{source.stem}-w{window}-b{band}.npz"
                np.savez_compressed(output / name, image=image)
                cases.append({"file": name, "source": source.name, "source_seconds": len(samples) / sr,
                              "window_s": window, "hop_s": hop, "bins_per_octave": bins,
                              "image_shape": list(image.shape)})
        print(f"Prepared actual spectra: {source.name}", flush=True)
    (output / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")


def path_from_result(result, maximum_velocity):
    _, t, j, v, back = result
    path = []
    while True:
        path.append((t, j))
        change = int(back[t, j, v])
        if change == 127 or t == 0:
            return np.asarray(path[::-1], dtype=int)
        j -= v - maximum_velocity
        v += change
        t -= 1


def benchmark(inputs, output, iterations):
    output.mkdir(parents=True, exist_ok=False)
    cases = json.loads((inputs / "cases.json").read_text())
    rows = []
    # JIT warm-up uses an actual source-derived submatrix, without generated data.
    first_image = np.load(inputs / cases[0]["file"])["image"]
    for kernel in (_curved_forward_reference, _curved_forward):
        kernel(np.ascontiguousarray(first_image[:, :32].T), 3, 1.5)
    for case in cases:
        image = np.load(inputs / case["file"])["image"].copy()
        rate = 0.05 if case["bins_per_octave"] > 144 else 0.3
        vmax = max(2, math.ceil(rate * case["hop_s"] * case["bins_per_octave"] / math.log(2)))
        old_time, new_time, calls, state_bytes = 0.0, 0.0, 0, 0
        for iteration in range(iterations):
            measured = np.ascontiguousarray(image.T)
            results = {}
            # Alternate call order to avoid giving one implementation all warm-cache starts.
            order = (("old", _curved_forward_reference), ("new", _curved_forward))
            if iteration % 2:
                order = order[::-1]
            for name, kernel in order:
                start = time.perf_counter()
                results[name] = kernel(measured, vmax, 1.5)
                elapsed = time.perf_counter() - start
                if name == "old":
                    old_time += elapsed
                else:
                    new_time += elapsed
            old, new = results["old"], results["new"]
            if old[:4] != new[:4] or not np.array_equal(old[4], new[4]):
                raise AssertionError(f"Recurrence mismatch at {case['file']} iteration {iteration}")
            old_path = path_from_result(old, vmax)
            new_path = path_from_result(new, vmax)
            np.testing.assert_array_equal(old_path, new_path)
            calls += 1
            state_bytes = old[4].nbytes
            # This is the production mask for the next extraction, not generated field data.
            cols, frequencies = old_path.T
            for offset in range(-2, 3):
                image[np.clip(frequencies + offset, 0, len(image) - 1), cols] = -4.0
            if old[0] < 25:
                break
        row = dict(case, calls=calls, reference_s=old_time, optimized_s=new_time,
                   speedup=old_time / new_time, backpointer_bytes=state_bytes,
                   exact_scores_indices_backpointers_paths=True)
        rows.append(row)
        print(json.dumps(row), flush=True)
    result = {"scope": "Real recorded spectra and unchanged iterative masks; no detector threshold or accuracy change",
              "cases": rows, "reference_s": sum(row["reference_s"] for row in rows),
              "optimized_s": sum(row["optimized_s"] for row in rows)}
    result["aggregate_speedup"] = result["reference_s"] / result["optimized_s"]
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}), flush=True)


def pipeline(source, output):
    """Compare complete discovery outputs, changing only the private kernel."""
    from dopplergeist import advanced_discovery
    from dopplergeist.discovery import discover_events
    from dopplergeist.intake import intake_recording

    output.mkdir(parents=True, exist_ok=False)
    recording = intake_recording(source, output / "intake")
    original = advanced_discovery._curved_forward
    outputs, timings = {}, {}
    try:
        for name, kernel in (("reference", _curved_forward_reference), ("optimized", original)):
            advanced_discovery._curved_forward = kernel
            destination = output / name
            started = time.perf_counter()
            discover_events(recording, output_dir=destination, plot_summary=False,
                            plot_event_details=False, event_audio=False)
            timings[name] = time.perf_counter() - started
            outputs[name] = json.loads((destination / "discovery.json").read_text())
            print(f"Finished complete discovery: {name}", flush=True)
    finally:
        advanced_discovery._curved_forward = original
    if outputs["reference"] != outputs["optimized"]:
        raise AssertionError("Complete automatic discovery outputs differ")
    result = {"source": Path(source).name, "source_seconds": recording.metadata["duration_s"],
              "events": len(outputs["optimized"]["events"]),
              "groups": len(outputs["optimized"]["proposals"]),
              "exact_complete_discovery": True, "elapsed_s": timings,
              "scope": "One complete real recording; parity check, not a pipeline speed estimate or location result"}
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "benchmark", "pipeline"))
    parser.add_argument("--data", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=32)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 32:
        parser.error("Use one to 32 production extractions")
    if args.command == "prepare":
        if args.data is None:
            parser.error("--data is required")
        prepare(args.data, args.output)
    elif args.command == "pipeline":
        if args.source is None:
            parser.error("--source is required")
        pipeline(args.source, args.output)
    else:
        if args.inputs is None:
            parser.error("--inputs is required")
        benchmark(args.inputs, args.output, args.iterations)


if __name__ == "__main__":
    main()
