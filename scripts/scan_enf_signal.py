"""Measure 50/60 Hz harmonic-tone availability in real recordings.

This scanner does not identify grid hum, match a reference, or estimate UTC.
Use a new output directory for each run; do not use its results as search time
evidence.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from dopplergeist.audio import decode
from dopplergeist.enf import scan_enf_tones, summarize_enf_tones


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="real audio files to screen")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="new directory for scan receipts and CSV evidence")
    parser.add_argument("--sample-rate", type=int, default=4000)
    parser.add_argument("--frame-s", type=float, default=4.0)
    parser.add_argument("--hop-s", type=float, default=1.0)
    parser.add_argument("--nominals", type=float, nargs="+", default=(50.0, 60.0))
    parser.add_argument("--harmonics", type=int, nargs="+", default=(1, 2, 3))
    parser.add_argument("--prominence-db", type=float, default=10.0,
                        help="screening threshold for local peak prominence, not an ENF confidence")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError("Use a new output directory to preserve prior scan evidence")
    if len(set(args.inputs)) != len(args.inputs):
        raise ValueError("Input paths must be unique")
    for path in args.inputs:
        if not path.is_file():
            raise FileNotFoundError(path)

    args.output_dir.mkdir(parents=True)
    trace_dir = args.output_dir / "traces"
    trace_dir.mkdir()
    summary_rows = []
    receipts = []
    for source in args.inputs:
        source = source.resolve()
        source_digest = sha256(source)
        samples, sr = decode(source, sample_rate=args.sample_rate)
        traces = scan_enf_tones(samples, sr, nominals=args.nominals, harmonics=args.harmonics,
                                frame_s=args.frame_s, hop_s=args.hop_s)
        estimates = summarize_enf_tones(traces, prominence_threshold_db=args.prominence_db)
        stem = f"{source.stem}-{source_digest[:12]}"
        trace_path = trace_dir / f"{stem}.csv"
        with trace_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("offset_s", "nominal_hz", "harmonic",
                                                        "target_hz", "frequency_hz",
                                                        "local_prominence_db"))
            writer.writeheader()
            writer.writerows(traces)
        for estimate in estimates:
            summary_rows.append({"source": str(source), "source_sha256": source_digest,
                                 "duration_s": len(samples) / sr, **estimate})
        receipts.append({"source": str(source), "source_sha256": source_digest,
                         "sample_rate_hz": sr, "duration_s": len(samples) / sr,
                         "trace_csv": str(trace_path.relative_to(args.output_dir)),
                         "harmonic_summaries": estimates})
        print(f"scanned {source.name}: {len(samples) / sr:.1f} s, {len(traces)} tone observations")

    with (args.output_dir / "summary.csv").open("w", newline="") as stream:
        columns = ("source", "source_sha256", "duration_s", "nominal_hz", "harmonic", "target_hz",
                   "frames", "prominence_threshold_db", "prominent_frame_fraction",
                   "median_local_prominence_db", "median_peak_frequency_hz",
                   "peak_frequency_std_hz", "peak_frequency_p05_hz", "peak_frequency_p95_hz",
                   "interpretation")
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(summary_rows)
    (args.output_dir / "receipt.json").write_text(json.dumps({
        "schema_version": 1, "method": "windowed FFT peak screen; not ENF identification",
        "sample_rate_hz": args.sample_rate, "frame_s": args.frame_s, "hop_s": args.hop_s,
        "nominals_hz": args.nominals, "harmonics": args.harmonics,
        "prominence_threshold_db": args.prominence_db,
        "reference_match_performed": False, "utc_estimate_emitted": False,
        "inputs": receipts,
    }, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
