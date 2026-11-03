"""Discovery-only adapter for DG-02's label-free subprocess benchmark runner."""
import argparse
import hashlib
import json
from pathlib import Path

from aircraft_geoloc.contracts import validate_request, validate_result
from aircraft_geoloc.discovery import DiscoverySettings, discover_events
from aircraft_geoloc.intake import intake_recording


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    request = validate_request(json.loads(args.request.read_text()))
    source = Path(request["audio_path"])
    if not source.is_absolute():
        source = args.request.parent / source
    args.output.mkdir(parents=True, exist_ok=True)
    recording = intake_recording(source, args.output / "intake", time_window=request.get("time_window"))
    events = discover_events(recording, output_dir=args.output / "discovery", settings=DiscoverySettings(min_contrast=2.5))
    result = validate_result({"schema_version": 1, "job_id": args.output.name,
        "status": "inconclusive", "stage": "discovery", "events": events,
        "reason_code": "discovery_only", "message": "Audio discovery evaluated; no historical flight matching or localization performed.",
        "artifacts": {"recording": "intake/recording.json", "discovery": "discovery/discovery.json"}})
    (args.output / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    modules = ("intake.py", "discovery.py", "contracts.py")
    code = Path("/home/cinna/dopplergeist-w1-audio/src/aircraft_geoloc")
    provenance = {"source_sha256": recording.metadata["source_sha256"],
                  "code_sha256": {name: hashlib.sha256((code / name).read_bytes()).hexdigest() for name in modules},
                  "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.output / "discovery-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
