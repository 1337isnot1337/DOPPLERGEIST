import argparse
import json
from pathlib import Path
import time

from dopplergeist.advanced_discovery import discover
from dopplergeist.intake import intake_recording
from dopplergeist.resource_usage import process_peak_rss_kib


def main():
    parser = argparse.ArgumentParser(description="Discover moving acoustic contours in a recording")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    recording = intake_recording(args.audio, args.output / "intake", sample_rate_hz=4000)
    auxiliary = intake_recording(args.audio, args.output / "intake_high", sample_rate_hz=24000)
    result = discover(recording, args.output, "ridge_dp_accel_broad_final_v25", aux_recording=auxiliary)
    result.update(recording=recording.metadata, runtime_s=time.monotonic() - start,
                  peak_rss_kib=process_peak_rss_kib())
    (args.output / "predictions.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"proposals": len(result["events"]), "output": str(args.output / "predictions.json")}))


if __name__ == "__main__":
    main()
