#!/usr/bin/env python3
"""Restore regional-replay bundles through the shared release restorer."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("data-source.tar.gz", "data-adsb-derived.tar.gz", "data-terrain.tar.gz")
SHARED_PATH = Path(__file__).with_name("restore_artifacts.py")
_SPEC = importlib.util.spec_from_file_location("checkpoint_shared_restorer", SHARED_PATH)
SHARED = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SHARED)
TAG = SHARED.TAG


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def restore_archive(archive: Path, asset: dict, destination: Path) -> int:
    """Use shared validation in staging, then publish only new destination files."""
    destination = destination.resolve()
    expected = {item["path"]: item for item in asset["files"]}
    if len(expected) != len(asset["files"]):
        raise ValueError("Duplicate paths in manifest")
    for name in expected:
        target = SHARED.destination(destination, name)
        if target.suffix.lower() == ".mp4":
            raise ValueError("Video files are outside the replay bundle contract")
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Refusing to overwrite {target}")
        for parent in target.parents:
            if parent == destination:
                break
            if (parent.exists() or parent.is_symlink()) and not parent.is_dir():
                raise FileExistsError(f"Destination parent is not a directory: {parent}")
    with tempfile.TemporaryDirectory(prefix=".checkpoint-staging-", dir=destination) as temporary:
        staging = Path(temporary)
        shared_asset = dict(asset, name=asset.get("name", archive.name))
        restored = SHARED.restore_asset(archive, shared_asset, staging)
        # Every archive member has passed the shared hash/size/path checks.
        # Same-filesystem hard links create each destination atomically without
        # replacing an existing file, including one created after preflight.
        for name in sorted(expected):
            target = SHARED.destination(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(staging / name, target)
    return restored["files"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT)
    parser.add_argument("--repository", default=SHARED.REPOSITORY)
    parser.add_argument("--manifest", type=Path, default=ROOT / "evidence/artifact-manifest.json")
    parser.add_argument("--receipt", type=Path, default=ROOT / "results/ci-restore.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("repository must be owner/name")
    if args.receipt.exists() or args.receipt.is_symlink():
        raise FileExistsError(f"Refusing to overwrite receipt {args.receipt}")
    args.destination.mkdir(parents=True, exist_ok=True)
    cache = args.destination / ".artifacts-ci"
    cache.mkdir(exist_ok=True)
    manifest = json.loads(args.manifest.read_text())
    indexed = {asset["name"]: asset for asset in manifest["assets"]}
    # The shared downloader invokes gh without a shell. gh receives its existing
    # authentication configuration or GH_TOKEN; no credential is recorded here.
    SHARED.REPOSITORY = args.repository
    receipt = {"release_tag": TAG, "repository": args.repository,
               "manifest_sha256": digest(args.manifest), "assets": [],
               "restoration_implementation": {"path": SHARED_PATH.name,
                   "sha256": digest(SHARED_PATH), "download": "gh release download",
                   "credentials_recorded": False},
               "scope": "source-informed regional replay; independent clock unverified"}
    started = time.perf_counter()
    try:
        for name in ASSETS:
            record = indexed[name]
            print(f"Verifying/downloading {name} ({record['bytes']} bytes)", flush=True)
            archive = SHARED.download_asset(record, cache)
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
        with args.receipt.open("x", encoding="utf-8") as output:
            output.write(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
