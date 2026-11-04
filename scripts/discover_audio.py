"""Run blind full-file intake/discovery into a fresh diagnostic directory.

No annotations, coordinates, flight IDs or per-case frequency/time hints are read.
Evaluate its output against withheld labels in a separate process.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import time

from dopplergeist.discovery import DiscoverySettings, discover_events, required_sample_rate
from dopplergeist.intake import intake_recording
from dopplergeist.resource_usage import process_peak_rss_kib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio")
    parser.add_argument("--output", required=True)
    parser.add_argument("--plot-summary", action="store_true",
                        help="render the recording-level ridge overview plot")
    parser.add_argument("--plot-event-details", action="store_true",
                        help="render one spectrogram PNG per discovered event (slower)")
    parser.add_argument("--min-frequency-hz", type=float, default=40.0)
    parser.add_argument("--max-frequency-hz", type=float, default=1600.0)
    parser.add_argument("--window-s", type=float, default=2.0)
    parser.add_argument("--hop-s", type=float, default=.5)
    parser.add_argument("--detailed-candidates", action="store_true", help="bounded rejected-candidate measurements")
    args = parser.parse_args()
    settings = DiscoverySettings(min_frequency_hz=args.min_frequency_hz, max_frequency_hz=args.max_frequency_hz,
                                 window_s=args.window_s, hop_s=args.hop_s)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    recording = intake_recording(args.audio, output / "intake", sample_rate_hz=required_sample_rate(settings))
    events = discover_events(recording, output_dir=output / "discovery",
                             plot_summary=args.plot_summary,
                             plot_event_details=args.plot_event_details, settings=settings, detailed_candidates=args.detailed_candidates)
    root = Path(__file__).resolve().parents[1]
    sources = sorted((root / "src" / "dopplergeist").glob("*.py"))
    code_hash = hashlib.sha256()
    for path in sources:
        code_hash.update(path.name.encode())
        code_hash.update(path.read_bytes())
    result = {"schema_version": 2, "recording": recording.metadata, "time_status": recording.time_status,
              "settings": asdict(settings), "events_found": len({e["harmonic_group_id"] for e in events}),
              "canonical_proposals": len({e["harmonic_group_id"] for e in events}), "measured_child_tracks": len(events),
              "events": [{k: event[k] for k in ("event_id", "start_s", "end_s", "band_hz", "quality")} for event in events],
              "runtime_s": time.monotonic() - began, "peak_rss_kib": process_peak_rss_kib(),
              "code_sha256": code_hash.hexdigest(),
              "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              "working_tree": subprocess.check_output(["git", "status", "--short"], cwd=root, text=True).strip(),
              "scope": "Blind acoustic discovery only; no aircraft association or location estimate"}
    (output / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
