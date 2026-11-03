"""Package the existing research checkpoint; no network or publishing side effects."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    groups = {name: [] for name in (
        "data-source", "data-research", "data-terrain", "data-synthetic",
        "data-adsb-derived", "results")}
    raw = []
    excluded = []
    for folder in ("data", "results"):
        for path in sorted((root / folder).rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".avi"}:
                excluded.append({"path": str(relative), "reason": "User excluded video"})
                continue
            if path.is_symlink():
                raise ValueError(f"Unexpected symlink: {relative}")
            if ".tar.a" in path.name and relative.parts[:2] == ("data", "adsb"):
                raw.append(path)
                continue
            group = "results" if folder == "results" else "-".join(relative.parts[:2])
            if group == "data-adsb":
                group = "data-adsb-derived"
            groups[group].append(path)
    manifest = {
        "checkpoint": "2026-11-02",
        "video_mp4_included": False,
        "reference_wav_included": True,
        "excluded": excluded,
        "assets": [],
    }
    metadata_keys = {
        "id", "title", "fulltitle", "description", "webpage_url", "uploader",
        "uploader_id", "uploader_url", "channel", "channel_id", "channel_url",
        "upload_date", "timestamp", "duration", "duration_string", "language",
        "license", "availability", "extractor", "extractor_key", "epoch",
        "width", "height", "fps", "asr", "audio_channels", "vcodec", "acodec",
    }
    for name, paths in groups.items():
        destination = output / f"{name}.tar.gz"
        files = []
        with tarfile.open(destination, "w:gz", compresslevel=1) as archive:
            for path in paths:
                relative = str(path.relative_to(root))
                entry = {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}
                if path.name in {"video.info.json", "reference-recording.info.json"}:
                    source = json.loads(path.read_text())
                    clean = {key: value for key, value in source.items() if key in metadata_keys}
                    clean["export_note"] = "Descriptive metadata only; transient media/request fields omitted."
                    payload = (json.dumps(clean, indent=2) + "\n").encode()
                    entry["original_bytes"] = entry["bytes"]
                    entry["original_sha256"] = entry["sha256"]
                    entry["bytes"] = len(payload)
                    entry["sha256"] = hashlib.sha256(payload).hexdigest()
                    entry["transformation"] = "descriptive_metadata_only"
                    info = archive.gettarinfo(str(path), arcname=relative)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
                else:
                    archive.add(path, arcname=relative, recursive=False)
                files.append(entry)
        manifest["assets"].append({"name": destination.name, "bytes": destination.stat().st_size,
                                   "sha256": digest(destination), "files": files})
        print(f"Packaged {destination.name}: {len(files)} files, {destination.stat().st_size} bytes", flush=True)
    for path in raw:
        destination = output / path.name
        os.link(path, destination)
        checksum = digest(destination)
        entry = {"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": checksum}
        manifest["assets"].append({"name": destination.name, "bytes": entry["bytes"],
                                   "sha256": checksum, "restore_path": entry["path"], "files": [entry]})
        print(f"Linked {destination.name}: {entry['bytes']} bytes", flush=True)
    if any(asset["bytes"] >= 2 * 1024**3 for asset in manifest["assets"]):
        raise ValueError("An asset exceeds the release size limit; split before publishing")
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    checksums = [f"{asset['sha256']}  {asset['name']}" for asset in manifest["assets"]]
    checksums.append(f"{digest(manifest_path)}  manifest.json")
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
    print(f"Complete: {len(manifest['assets'])} assets; no video files included", flush=True)


if __name__ == "__main__":
    main()
