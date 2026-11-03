"""Audit published six-event evidence without rerunning or changing its decision."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sqlite3
import subprocess
import tarfile
import time
import zipfile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_path(name):
    path = PurePosixPath(name)
    assert not path.is_absolute() and ".." not in path.parts, name
    assert name == path.as_posix(), name
    return path


def save_once(path, raw):
    if path.exists():
        assert path.read_bytes() == raw, f"Existing different bytes: {path}"
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def verify_tar(path, specification, destination, prefix="", select=lambda name: True):
    assert path.stat().st_size == specification["bytes"]
    assert file_digest(path) == specification["sha256"]
    expected = {entry["path"]: entry for entry in specification["files"]}
    assert len(expected) == len(specification["files"])
    checked, seen = [], set()
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            safe_path(member.name)
            assert member.isfile(), f"Nonregular archive member: {member.name}"
            assert member.name.startswith(prefix)
            name = member.name[len(prefix):]
            assert name in expected and name not in seen, name
            seen.add(name)
            reference = expected[name]
            assert member.size == reference["bytes"], name
            stream = archive.extractfile(member)
            raw = stream.read() if select(name) else None
            sha = digest(raw) if raw is not None else hashlib.file_digest(stream, "sha256").hexdigest()
            assert sha == reference["sha256"], name
            if raw is not None:
                save_once(destination / name, raw)
            checked.append({"path": name, "bytes": member.size, "sha256": sha})
    assert seen == set(expected)
    return {"archive_sha256": specification["sha256"], "members_verified": len(checked),
            "uncompressed_bytes": sum(entry["bytes"] for entry in checked), "files": checked}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    root = args.root.resolve()
    release = json.loads((root / "release-manifest.json").read_bytes())
    canonical = json.loads((root / "canonical-release-manifest.json").read_bytes())
    release_spec = release["assets"][0]
    canonical_spec = next(entry for entry in canonical["assets"] if entry["name"] == "multi-event-6.tar.gz")
    out = {"scope": "Passive archive integrity, frozen runtime and checkpoint accounting; no new pipeline run or acceptance change.",
           "checked_at_utc": datetime.now(timezone.utc).isoformat(),
           "runtime_commit": release["runtime_commit"],
           "audit_script_sha256": file_digest(Path(__file__)),
           "manifest_sha256": {name: file_digest(root / name) for name in
                               ("release-manifest.json", "canonical-release-manifest.json")}}
    out["release"] = verify_tar(root / "release.tar.gz", release_spec, root / "restored")
    out["canonical"] = verify_tar(root / "canonical-six.tar.gz", canonical_spec, root / "canonical",
                                  prefix="multi-event-6/", select=lambda name: name.startswith("inputs/"))
    runtime = json.loads((root / "restored/verification/installed-runtime-manifest.json").read_bytes())
    wheel = root / "restored/runtime/aircraft_geoloc_reproduction-0.1.0-py3-none-any.whl"
    assert file_digest(wheel) == release["wheel_sha256"] == runtime["wheel_sha256"]
    source_checks = []
    expected_wheel = {entry["path"].removeprefix("src/"): entry for entry in runtime["files"]}
    with zipfile.ZipFile(wheel) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist()))
        names = {name for name in archive.namelist() if name.startswith("aircraft_geoloc/")}
        assert names == set(expected_wheel)
        for name in archive.namelist():
            safe_path(name)
            assert not archive.getinfo(name).is_dir()
            raw = archive.read(name)
            if name in expected_wheel:
                entry = expected_wheel[name]
                source = subprocess.check_output(["git", "show", f"{release['runtime_commit']}:{entry['path']}"], cwd=args.repo)
                assert digest(raw) == entry["sha256"] == digest(source), name
                source_checks.append({"path": entry["path"], "sha256": digest(raw)})
            save_once(root / "frozen-runtime" / name, raw)
    out["wheel"] = {"sha256": file_digest(wheel), "source_files_verified": len(source_checks), "files": source_checks}
    checkpoint_manifest = root / "restored/coarse/tile-checkpoints.jsonl"
    records = [json.loads(line) for line in checkpoint_manifest.read_text().splitlines() if line.strip()]
    expected = {record["path"]: record for record in records}
    assert len(expected) == len(records)
    report = json.loads((root / "restored/verification/terminal-search-search-report.json").read_bytes())
    seen, run_hashes, group_counts = set(), Counter(), Counter()
    grid_points = ranked_rows = populated_tiles = tracks_evaluated = 0
    tile_rankings = []
    with tarfile.open(root / "restored/coarse/tile-checkpoints.tar.gz", "r|gz") as archive:
        for member in archive:
            safe_path(member.name)
            assert member.isfile() and member.name in expected and member.name not in seen, member.name
            seen.add(member.name)
            raw = archive.extractfile(member).read()
            record = expected[member.name]
            assert len(raw) == record["bytes"] == member.size
            assert digest(raw) == record["sha256"], member.name
            checkpoint = json.loads(raw)
            payload = checkpoint["payload"]
            payload_hash = digest(json.dumps(payload, sort_keys=True, allow_nan=False).encode())
            assert payload_hash == checkpoint["payload_hash"], member.name
            assert checkpoint["run_hash"] == report["run_hash"], member.name
            run_hashes[checkpoint["run_hash"]] += 1
            grid_points += payload["grid_points"]
            tracks_evaluated += payload["tracks"]
            ranked_rows += len(payload["ranked"])
            if payload["ranked"]:
                populated_tiles += 1
                tile_rankings.append(payload["ranked"])
                group_counts.update(len(row.get("event_indices", [])) for row in payload["ranked"])
    assert seen == set(expected)
    assert len(seen) == report["tiles_completed"] == report["tiles_total"]
    assert grid_points == report["grid_points_searched"]
    assert report["unsearched_tiles"] == 0 and report["tile_failures"] == []
    out["checkpoints"] = {"members_verified": len(seen), "payload_hashes_verified": len(seen),
                          "run_hashes": dict(run_hashes), "grid_points": grid_points,
                          "tiles_with_ranked_rows": populated_tiles, "ranked_row_occurrences": ranked_rows,
                          "event_group_counts": dict(sorted(group_counts.items())),
                          "track_work_evaluations": tracks_evaluated,
                          "all_native_completeness_counts_match": True}
    # Query only the independently hash-verified frozen index, always read-only.
    index = root / "restored/derived-inputs/flights-runtime-v2.sqlite"
    with sqlite3.connect(index.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        metadata = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        segments = 0
        for name, payload, sha in db.execute("SELECT name,payload,payload_hash FROM segments"):
            assert digest(payload) == sha, name
            segments += 1
    canonical_tracks = next(entry for entry in canonical_spec["files"] if entry["path"] == "inputs/tracks.parquet")
    assert any(source.get("sha256") == canonical_tracks["sha256"] for source in metadata["sources"])
    out["index"] = {"sha256": file_digest(index), "sqlite_integrity": "ok", "segment_payloads_verified": segments,
                    "canonical_tracks_source_hash_matches": True, "metadata": metadata}
    save_once(root / "coarse-rankings-for-replay.json", (json.dumps(tile_rankings) + "\n").encode())
    out["elapsed_s"] = time.monotonic() - started
    (root / "archive-audit.json").write_text(json.dumps(out, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"release_members": out["release"]["members_verified"],
                      "canonical_members": out["canonical"]["members_verified"],
                      "wheel_source_files": len(source_checks), "checkpoints": out["checkpoints"],
                      "index_segments": segments, "elapsed_s": out["elapsed_s"]}))


if __name__ == "__main__":
    main()
