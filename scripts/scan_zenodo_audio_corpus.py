"""Blind whole-recording Doppler scan for public Zenodo WAV corpora.

This runner reads audio files only. It deliberately accepts no time, location,
flight-track, or event-label inputs and performs no matching or geolocation.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from dopplergeist.discovery import DiscoverySettings, discover_events
from dopplergeist.intake import intake_recording


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan(audio_root, output_dir):
    audio_root = Path(audio_root).resolve()
    output_dir = Path(output_dir).resolve()
    if not audio_root.is_dir():
        raise ValueError("audio_root must be a directory")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("Output directory must be new or empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    blind_inputs = output_dir / "blind-inputs"
    blind_inputs.mkdir()
    scan_root = output_dir / "scans"
    scan_root.mkdir()

    sources = sorted(path for path in audio_root.rglob("*.wav")
                     if "__MACOSX" not in path.parts and not path.name.startswith("._"))
    if not sources:
        raise ValueError("No WAV files found")

    settings = DiscoverySettings()
    rows = []
    for source in sources:
        digest = _sha256(source)
        clip_id = f"sha256-{digest[:16]}"
        blind_audio = blind_inputs / f"{clip_id}.wav"
        if not blind_audio.exists():
            blind_audio.symlink_to(source)
        recording = intake_recording(blind_audio, output_dir / "intake" / clip_id)
        events = discover_events(recording, settings=settings, plot_summary=False,
                                 plot_event_details=False)
        groups = sorted({event["harmonic_group_id"] for event in events})
        result = {
            "clip_id": clip_id,
            "source_sha256": digest,
            "duration_s": recording.metadata["duration_s"],
            "sample_rate_hz": recording.metadata["sample_rate_hz"],
            "channels": recording.metadata["channels"],
            "time_window_used": False,
            "flight_data_used": False,
            "location_data_used": False,
            "status": "proposals" if events else "no_proposals",
            "proposal_count": len(events),
            "harmonic_group_count": len(groups),
            "aircraft_identity_confirmed": False,
            "settings": settings.__dict__,
            "events": events,
        }
        (scan_root / f"{clip_id}.json").write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n")
        rows.append({key: result[key] for key in (
            "clip_id", "source_sha256", "duration_s", "sample_rate_hz", "channels",
            "status", "proposal_count", "harmonic_group_count", "aircraft_identity_confirmed")})
        print(clip_id, result["status"], len(events), len(groups), flush=True)

    with (output_dir / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "source": "https://zenodo.org/records/23424278",
        "scope": "whole-recording audio intake and acoustic Doppler proposals only",
        "selection": "all WAV files under audio_root, sorted by relative path",
        "ground_truth_inputs_used": False,
        "flight_matching_or_geolocation_run": False,
        "settings": settings.__dict__,
        "clip_count": len(rows),
    }
    (output_dir / "scan-manifest.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    scan(args.audio_root, args.output_dir)


if __name__ == "__main__":
    main()
