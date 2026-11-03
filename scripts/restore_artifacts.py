"""Download selected checkpoint assets, verify hashes, and restore without overwrites."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "1337isnot1337/DOPPLERGEIST"
TAG = "checkpoint-2026-11-02"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def destination(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or not relative.parts or relative.parts[0] not in ("data", "results"):
        raise ValueError(f"Unsafe artifact path: {name}")
    target = root / str(relative)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Artifact path escapes destination through a symlink: {name}")
    return target


def verify_file(path, entry):
    if not path.is_file() or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError(f"Checksum/size mismatch: {path}")


def _write_file(stream, target, entry):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".restore-", delete=False) as output:
            temporary = Path(output.name)
            shutil.copyfileobj(stream, output, length=1024 * 1024)
        verify_file(temporary, entry)
        if target.exists():
            verify_file(target, entry)  # A concurrent writer must have identical content.
        else:
            os.link(temporary, target)  # Atomic create: never replace an existing file.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def restore_asset(asset_path, asset, root):
    root = Path(root).resolve()
    asset_path = Path(asset_path)
    verify_file(asset_path, asset)
    entries = {entry["path"]: entry for entry in asset["files"]}
    if len(entries) != len(asset["files"]):
        raise ValueError("Duplicate paths in artifact manifest")
    existing = set()
    for name, entry in entries.items():
        target = destination(root, name)
        if target.exists():
            verify_file(target, entry)  # Refuse conflicting local files before extracting anything.
            existing.add(name)
    if asset_path.name.endswith(".tar.gz"):
        seen = set()
        with tarfile.open(asset_path, "r|gz") as archive:
            for member in archive:
                if not member.isfile() or member.name not in entries or member.name in seen:
                    raise ValueError(f"Unexpected archive member: {member.name}")
                entry = entries[member.name]
                if member.size != entry["bytes"]:
                    raise ValueError(f"Archive member size mismatch: {member.name}")
                if member.name not in existing:
                    with archive.extractfile(member) as stream:
                        _write_file(stream, destination(root, member.name), entry)
                seen.add(member.name)
        if seen != entries.keys():
            raise ValueError("Archive is missing manifest files")
    else:
        name = asset["restore_path"]
        if set(entries) != {name}:
            raise ValueError("Raw asset must have one restore path")
        if name not in existing:
            with asset_path.open("rb") as stream:
                _write_file(stream, destination(root, name), entries[name])
    return {"asset": asset["name"], "files": len(entries), "already_present": len(existing)}


def download_asset(asset, cache):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / asset["name"]
    if path.exists():
        verify_file(path, asset)
        return path
    with tempfile.TemporaryDirectory(dir=cache, prefix=".download-") as temporary:
        subprocess.run(["gh", "release", "download", TAG, "--repo", REPOSITORY,
                        "--pattern", asset["name"], "--dir", temporary], check=True)
        fetched = Path(temporary) / asset["name"]
        verify_file(fetched, asset)
        if path.exists():
            verify_file(path, asset)
        else:
            os.link(fetched, path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", action="append", default=[], help="Asset name or bundle stem; repeat as needed")
    parser.add_argument("--all", action="store_true", help="Restore all assets (over 6 GB download)")
    parser.add_argument("--list", action="store_true", help="List available assets without downloading")
    parser.add_argument("--cache", type=Path, default=ROOT / ".artifacts")
    parser.add_argument("--destination", type=Path, default=ROOT)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "evidence/artifact-manifest.json").read_text())
    assets = manifest["assets"]
    if args.list:
        for asset in assets:
            print(f"{asset['name']}\t{asset['bytes']} bytes\t{len(asset['files'])} files")
        return
    by_name = {asset["name"]: asset for asset in assets}
    aliases = {name.removesuffix(".tar.gz"): name for name in by_name}
    names = list(by_name) if args.all else list(dict.fromkeys(aliases.get(name, name) for name in args.bundle))
    if not names or any(name not in by_name for name in names):
        parser.error("Choose known --bundle names or --all; use --list for the inventory")
    for name in names:
        asset = by_name[name]
        print(f"Verifying/downloading {name}", flush=True)
        path = download_asset(asset, args.cache.resolve())
        print(json.dumps(restore_asset(path, asset, args.destination)), flush=True)


if __name__ == "__main__":
    main()
