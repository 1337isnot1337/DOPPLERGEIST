"""One frozen-fit spectral validation experiment; no truth or search changes.

This script reads only the original automatic job's inputs, detections, retained
candidates, and trajectory index. It scores every retained association uniformly.
The result is a development diagnostic, not independent localization acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", type=Path, required=True)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.implementation / "src"))
    from aircraft_geoloc.audio import spectrogram
    from aircraft_geoloc.data_access import FlightIndex
    from aircraft_geoloc.geometry import ecef
    from aircraft_geoloc.matching import prepare_events

    began = time.monotonic()
    job, output = args.job.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metadata = json.loads((job / "intake/recording.json").read_text())
    discovery = json.loads((job / "discovery/discovery.json").read_text())
    config = json.loads((job / "operator.json").read_text())
    retained = json.loads((job / "refined-candidates.json").read_text())["ranked"]
    events, measurements = prepare_events(discovery["events"])
    sr, duration = metadata["sample_rate_hz"], metadata["duration_s"]
    samples = np.memmap(job / "intake/recording.f32", dtype="<f4", mode="r")
    c = float(config.get("sound_speed_mps", 343.0))

    # Freeze one best core-fit representative for every retained association.
    # Ranking here uses only the original core fit, never the validation samples.
    unique = {}
    for row in sorted(retained, key=lambda r: -r["score"]):
        key = (tuple(row.get("event_indices", range(len(events)))), tuple(row["flight_ids"]))
        unique.setdefault(key, row)
    candidates = [dict(row, diagnostic_id=f"A{i+1:02d}") for i, row in enumerate(unique.values())]
    if not candidates:
        raise ValueError("No retained associations to validate")
    if any(row.get("event_indices", list(range(len(events)))) != list(range(len(events))) for row in candidates):
        raise ValueError("This uniform experiment requires all candidates to explain the same events")
    tracks = {}
    indexes = [FlightIndex(path) for path in config["flight_indexes"]]
    for index in indexes:
        scope = index.report["coverage"]
        for track in index.query(scope["bounds"], scope["time_range_s"]):
            if track.id in tracks:
                raise ValueError("Duplicate track IDs require explicit source reconciliation")
            tracks[track.id] = track

    protocol = {
        "time_expansion_each_side_s": 120.0,
        "band_rule": "[0.5 * detected_low, 2 * detected_high], clipped to 40..1600 Hz",
        "spectral_window_s": 2.0,
        "spectral_hop_s": 0.25,
        "excluded_core_guard_s": 2.0,
        "sideband_offsets_hz": [-10.0, -5.0, 5.0, 10.0],
        "score": "predicted-curve contrast minus mean sideband contrast; equal event weighting",
        "sample_support": "identical bins with valid trajectories and all spectral samples for every association",
        "nuisance_parameters": "frozen original f0 and linear emission-time drift; no validation refit",
        "candidate_selection": "best original core-fit row for every retained event/flight association",
        "bootstrap": "2000 paired resamples of 10 s blocks within each event; descriptive only",
        "no_truth_read": True,
        "scope": "development diagnostic on an already inspected synthetic recording; not independent acceptance",
    }
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    spectra, evidence, arrays = [], [], {}
    for ei, (event, measurement) in enumerate(zip(events, measurements)):
        start = max(0.0, event["start_s"] - 120.0)
        end = min(duration, event["end_s"] + 120.0)
        band = [max(40.0, event["band_hz"][0] * 0.5), min(1600.0, event["band_hz"][1] * 2.0)]
        first, last = round(start * sr), round(end * sr)
        spec = spectrogram(np.asarray(samples[first:last]), sr, band, start=first / sr,
                           window_s=2.0, hop_s=0.25)
        on_curve, off_curve, predicted = [], [], []
        candidate_support = []
        for row in candidates:
            track = tracks[row["flight_ids"][ei]]
            observer = ecef(row["lat"], row["lon"], row["elev_m"])
            clock = row["recording_start_time_s"]
            core_t, _, core_w, _ = measurement
            core_emission = track.acoustic(clock + core_t.time[np.asarray(core_w) > 0], observer, c)[1]
            if not np.isfinite(core_emission).all():
                raise ValueError("A retained candidate lacks support for its fitted core")
            midpoint = (core_emission.min() + core_emission.max()) / 2
            factor, emission, _ = track.acoustic(clock + spec.time, observer, c)
            fit = row["event_diagnostics"][ei]
            source_frequency = fit["f0_hz"] + fit["source_drift_hz_s"] * (emission - midpoint)
            frequency = source_frequency * factor
            on = spec.sample(spec.time, frequency)
            off = np.mean([spec.sample(spec.time, frequency + offset)
                           for offset in protocol["sideband_offsets_hz"]], axis=0)
            predicted.append(frequency)
            on_curve.append(on)
            off_curve.append(off)
            candidate_support.append(np.isfinite(on) & np.isfinite(off))
        on_curve, off_curve, predicted = map(np.asarray, (on_curve, off_curve, predicted))
        common = np.logical_and.reduce(candidate_support)
        outside_core = np.ones(len(spec.time), dtype=bool)
        for original in discovery["events"]:
            outside_core &= ((spec.time < original["start_s"] - 2.0) |
                             (spec.time > original["end_s"] + 2.0))
        common &= outside_core
        if common.sum() < 40:
            raise ValueError("Too little common weak-wing support to compare associations")
        delta = on_curve - off_curve
        time_valid, delta_valid = spec.time[common], delta[:, common]
        pre = time_valid < event["start_s"]
        post = time_valid > event["end_s"]
        per_candidate = []
        for i, row in enumerate(candidates):
            per_candidate.append({
                "candidate_id": row["diagnostic_id"],
                "on_curve_mean": float(on_curve[i, common].mean()),
                "sideband_mean": float(off_curve[i, common].mean()),
                "contrast_excess_mean": float(delta_valid[i].mean()),
                "pre_core_excess": float(delta_valid[i, pre].mean()) if pre.any() else None,
                "post_core_excess": float(delta_valid[i, post].mean()) if post.any() else None,
            })
        evidence.append({
            "event_id": event["event_id"],
            "detected_core_s": [event["start_s"], event["end_s"]],
            "expanded_window_s": [start, end], "expanded_band_hz": band,
            "common_validation_samples": int(common.sum()),
            "common_validation_seconds": float(common.sum() * 0.25),
            "common_validation_extent_s": [float(time_valid[0]), float(time_valid[-1])],
            "pre_samples": int(pre.sum()), "post_samples": int(post.sum()),
            "scores": per_candidate,
        })
        spectra.append((event, spec, predicted, common, delta_valid, time_valid))
        for name, array in {"time": spec.time, "frequency": spec.frequency, "contrast": spec.contrast,
                            "predictions": predicted, "on_curve": on_curve, "sidebands": off_curve,
                            "common_validation_mask": common}.items():
            arrays[f"event_{ei+1}_{name}"] = array
        np.savetxt(output / f"event-{ei+1}-validation.csv",
                   np.column_stack((time_valid, delta_valid.T)), delimiter=",",
                   header="time_s," + ",".join(r["diagnostic_id"] for r in candidates), comments="")

    scores = np.mean([data[4].mean(axis=1) for data in spectra], axis=0)
    rng = np.random.default_rng(7231)
    bootstrap = np.zeros((2000, len(candidates)))
    for _, _, _, _, delta, times in spectra:
        blocks = np.floor(times / 10).astype(int)
        unique_blocks = np.unique(blocks)
        sums = np.array([delta[:, blocks == block].sum(axis=1) for block in unique_blocks])
        counts = np.array([(blocks == block).sum() for block in unique_blocks])
        selections = rng.integers(0, len(unique_blocks), size=(2000, len(unique_blocks)))
        bootstrap += sums[selections].sum(axis=1) / counts[selections].sum(axis=1)[:, None] / len(spectra)
    order = np.argsort(-scores, kind="stable")
    winner = int(order[0])
    summary = []
    for rank, index in enumerate(order, 1):
        row = candidates[index]
        difference = bootstrap[:, winner] - bootstrap[:, index]
        summary.append({"rank": rank, "candidate_id": row["diagnostic_id"],
                        "flight_ids": row["flight_ids"], "core_fit_score": row["score"],
                        "weak_support_score": float(scores[index]),
                        "winner_minus_candidate": float(scores[winner] - scores[index]),
                        "descriptive_block_interval_95": np.quantile(difference, [.025, .975]).tolist(),
                        "lat": row["lat"], "lon": row["lon"]})
    inputs = [job / name for name in ("input.mp3", "intake/recording.f32", "intake/recording.json",
              "discovery/discovery.json", "refined-candidates.json", "operator.json")]
    inputs += [index.path for index in indexes]
    report = {"protocol": protocol, "association_count": len(candidates),
              "retained_rows_considered": len(retained), "ranking": summary, "events": evidence,
              "implementation_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.implementation, text=True).strip(),
              "implementation_sources": {name: digest(args.implementation / "src/aircraft_geoloc" / name)
                                          for name in ("audio.py", "geometry.py", "matching.py", "data_access.py")},
              "inputs": [{"path": str(path), "sha256": digest(path)} for path in inputs],
              "script_sha256": digest(__file__), "elapsed_s": time.monotonic() - began,
              "limits": ["Settings were fixed for this one experiment after inspecting a development failure.",
                         "Candidate parameters and locations were not refitted on validation samples.",
                         "Linear source drift is extrapolated beyond its core fitting interval.",
                         "Common-support restriction is symmetric but conditional on the retained candidate set.",
                         "Block intervals are descriptive and are not calibrated localization confidence.",
                         "No ground-truth file was opened; no real-world accuracy or national-coverage acceptance is claimed."]}
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    np.savez_compressed(output / "spectral-evidence.npz", **arrays)

    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    fig, axes = plt.subplots(len(spectra), 1, figsize=(13, 4 * len(spectra)), layout="constrained")
    for axis, (event, spec, predicted, common, _, _) in zip(np.atleast_1d(axes), spectra):
        axis.pcolormesh(spec.time, spec.frequency, spec.contrast, shading="auto", cmap="magma", vmin=0, vmax=6, rasterized=True)
        for row, frequency in zip(candidates, predicted):
            axis.plot(spec.time, frequency, linewidth=1, label=row["diagnostic_id"])
        axis.axvspan(event["start_s"] - 2, event["end_s"] + 2, alpha=.22, color="white", label="Excluded fitted core")
        axis.set(xlabel="Recording time (s)", ylabel="Frequency (Hz)", title=event["event_id"] + ": fixed expanded window; frozen candidate curves")
        axis.legend(ncol=3, fontsize="small")
    fig.savefig(output / "expanded-spectra.png", dpi=140)
    plt.close(fig)
    print(json.dumps({"output": str(output), "ranking": summary, "events": evidence, "elapsed_s": report["elapsed_s"]}, indent=2))


if __name__ == "__main__":
    main()
