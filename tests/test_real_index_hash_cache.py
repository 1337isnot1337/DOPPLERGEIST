"""Digest-cache integrity controls using a restored real aircraft index."""
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from dopplergeist import data_access
from dopplergeist.data_access import FlightIndex, cached_sha256, sha256


@pytest.fixture
def observed_index(tmp_path):
    source = os.environ.get("DOPPLERGEIST_REAL_FLIGHT_INDEX")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_FLIGHT_INDEX to a restored real index")
    assert FlightIndex(source).report["segments"] > 0
    path = tmp_path / "observed.sqlite"
    shutil.copyfile(source, path)
    return path


def test_unchanged_real_index_reuses_verified_digest(observed_index, monkeypatch):
    expected = sha256(observed_index)
    original, calls = data_access.hashlib.file_digest, []

    def count(stream, algorithm):
        calls.append(stream.name)
        return original(stream, algorithm)

    monkeypatch.setattr(data_access.hashlib, "file_digest", count)
    assert cached_sha256(observed_index) == expected
    assert cached_sha256(observed_index) == expected
    assert calls == [str(observed_index)]


@pytest.mark.parametrize("existing_lock", [False, True])
def test_real_index_read_survives_unwritable_sidecars(observed_index, existing_lock, monkeypatch):
    expected = sha256(observed_index)
    receipt = observed_index.with_name(observed_index.name + ".sha256.json")
    if existing_lock:
        lock = receipt.with_name(receipt.name + ".lock")
        lock.touch()
        lock.chmod(0o666)
    original, calls = data_access.hashlib.file_digest, []

    def count(stream, algorithm):
        calls.append(stream.name)
        return original(stream, algorithm)

    monkeypatch.setattr(data_access.hashlib, "file_digest", count)
    observed_index.chmod(0o444)
    observed_index.parent.chmod(0o555)
    try:
        if os.access(observed_index.parent, os.W_OK):
            pytest.skip("current account bypasses read-only directory permissions")
        assert cached_sha256(observed_index) == expected
        assert calls == [str(observed_index)]
        assert not receipt.exists()
    finally:
        observed_index.parent.chmod(0o755)


def test_modified_real_index_is_rehashed_despite_restored_mtime(observed_index):
    before = observed_index.stat()
    old_digest = cached_sha256(observed_index)
    # Change only metadata in this disposable copy; recorded observations stay intact.
    with sqlite3.connect(observed_index) as database:
        metadata = json.loads(database.execute("SELECT value FROM metadata").fetchone()[0])
        metadata["digest_cache_test"] = "updated metadata"
        database.execute("UPDATE metadata SET value=?", (json.dumps(metadata),))
    os.utime(observed_index, ns=(before.st_atime_ns, before.st_mtime_ns))
    expected = sha256(observed_index)
    assert expected != old_digest
    assert cached_sha256(observed_index) == expected


@pytest.mark.parametrize("read_only_directory", [False, True])
def test_real_index_mutation_during_hash_is_rejected(observed_index, monkeypatch, read_only_directory):
    original = data_access.hashlib.file_digest

    def change_during_hash(stream, algorithm):
        digest = original(stream, algorithm)
        # Deliberately corrupt only the temporary copy after its bytes were read.
        with observed_index.open("ab") as changed:
            changed.write(b"\0")
        return digest

    monkeypatch.setattr(data_access.hashlib, "file_digest", change_during_hash)
    if read_only_directory:
        observed_index.parent.chmod(0o555)
    try:
        with pytest.raises(OSError, match="File changed while hashing"):
            cached_sha256(observed_index)
    finally:
        observed_index.parent.chmod(0o755)
    assert not observed_index.with_name(observed_index.name + ".sha256.json").exists()


def test_real_index_replacement_during_hash_is_rejected(observed_index, monkeypatch):
    replacement = observed_index.with_name("replacement.sqlite")
    shutil.copyfile(observed_index, replacement)
    original = data_access.hashlib.file_digest

    def replace_during_hash(stream, algorithm):
        digest = original(stream, algorithm)
        replacement.replace(observed_index)
        return digest

    monkeypatch.setattr(data_access.hashlib, "file_digest", replace_during_hash)
    with pytest.raises(OSError, match="File changed while hashing"):
        cached_sha256(observed_index)


def test_change_during_receipt_hit_rehashes_current_bytes(observed_index, monkeypatch):
    old_digest = cached_sha256(observed_index)
    original, calls = Path.stat, 0

    def stat(path, *args, **kwargs):
        nonlocal calls
        if path == observed_index:
            calls += 1
            if calls == 2:
                with observed_index.open("ab") as changed:
                    changed.write(b"\0")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    current = cached_sha256(observed_index)
    assert current != old_digest
    assert current == sha256(observed_index)
