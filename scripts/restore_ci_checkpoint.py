#!/usr/bin/env python3
"""Restore public regional-replay bundles against the committed manifest."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("data-source.tar.gz", "data-adsb-derived.tar.gz", "data-terrain.tar.gz")
TAG = "checkpoint-2026-11-02"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_file(path: Path, record: dict) -> None:
    if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
        raise ValueError(f"Checksum or size mismatch: {path}")


def restore_archive(archive: Path, asset: dict, destination: Path) -> int:
    """Validate every archive member before writing new destination files."""
    validate_file(archive, asset)
    destination = destination.resolve()
    expected = {item["path"]: item for item in asset["files"]}
    if len(expected) != len(asset["files"]):
        raise ValueError("Duplicate paths in manifest")
    with tempfile.TemporaryDirectory(prefix=".checkpoint-staging-", dir=destination) as tmp:
        staging = Path(tmp)
        seen = set()
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"Invalid archive path: {member.name}")
                if member.isdir():
                    continue
                if not member.isfile() or member.name not in expected or member.name in seen:
                    raise ValueError(f"Unexpected archive member: {member.name}")
                if relative.suffix.lower() == ".mp4":
                    raise ValueError("Video files are outside the replay bundle contract")
                target = destination.joinpath(*relative.parts)
                if target.exists() or target.is_symlink():
                    raise FileExistsError(f"Refusing to overwrite {target}")
                if not target.resolve().is_relative_to(destination):
                    raise ValueError(f"Target leaves destination: {target}")
                record = expected[member.name]
                if member.size != record["bytes"]:
                    raise ValueError(f"Member size mismatch: {member.name}")
                output = staging.joinpath(*relative.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, output.open("xb") as sink:
                    shutil.copyfileobj(source, sink, length=1024 * 1024)
                validate_file(output, record)
                seen.add(member.name)
        if seen != set(expected):
            raise ValueError(f"Missing manifest files: {sorted(set(expected) - seen)}")
        for name in sorted(seen):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with (staging / name).open("rb") as source, target.open("xb") as sink:
                shutil.copyfileobj(source, sink, length=1024 * 1024)
    return len(seen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT)
    parser.add_argument("--repository", default="1337isnot1337/DOPPLERGEIST")
    parser.add_argument("--manifest", type=Path, default=ROOT / "evidence/artifact-manifest.json")
    parser.add_argument("--receipt", type=Path, default=ROOT / "results/ci-restore.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("repository must be owner/name")
    args.destination.mkdir(parents=True, exist_ok=True)
    cache = args.destination / ".artifacts-ci"
    cache.mkdir(exist_ok=True)
    manifest = json.loads(args.manifest.read_text())
    indexed = {asset["name"]: asset for asset in manifest["assets"]}
    receipt = {"release_tag": TAG, "repository": args.repository,
               "manifest_sha256": digest(args.manifest), "assets": [],
               "scope": "source-informed regional replay; independent clock unverified"}
    started = time.perf_counter()
    try:
        for name in ASSETS:
            record = indexed[name]
            archive = cache / name
            if not archive.exists():
                url = f"https://github.com/{args.repository}/releases/download/{TAG}/{name}"
                request = urllib.request.Request(url, headers={"User-Agent": "DOPPLERGEIST-checkpoint-verifier"})
                partial = archive.with_suffix(archive.suffix + ".part")
                print(f"Downloading {name} ({record['bytes']} bytes)", flush=True)
                with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as sink:
                    shutil.copyfileobj(response, sink, length=1024 * 1024)
                validate_file(partial, record)
                partial.rename(archive)
            count = restore_archive(archive, record, args.destination)
            receipt["assets"].append({"name": name, "sha256": record["sha256"],
                                      "bytes": record["bytes"], "verified_files": count})
            print(f"Verified and restored {name}: {count} files", flush=True)
        receipt["status"] = "passed"
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt["elapsed_s"] = time.perf_counter() - started
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
