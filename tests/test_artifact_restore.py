import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile

import pytest


spec = importlib.util.spec_from_file_location("restore_artifacts", Path(__file__).resolve().parents[1] / "scripts/restore_artifacts.py")
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


def bundle(tmp_path, name="data/example/input.txt", payload=b"known evidence"):
    archive = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    entry = {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    asset = {"name": archive.name, "bytes": archive.stat().st_size, "sha256": restore.sha256(archive), "files": [entry]}
    return archive, asset


def test_verified_restore_reuses_identical_files_and_preserves_conflicts(tmp_path):
    archive, asset = bundle(tmp_path)
    root = tmp_path / "checkout"
    assert restore.restore_asset(archive, asset, root)["already_present"] == 0
    target = root / "data/example/input.txt"
    assert target.read_bytes() == b"known evidence"
    assert restore.restore_asset(archive, asset, root)["already_present"] == 1
    target.write_text("user changes")
    with pytest.raises(ValueError, match="mismatch"):
        restore.restore_asset(archive, asset, root)
    assert target.read_text() == "user changes"


def test_corrupt_bundle_does_not_write_destination(tmp_path):
    archive, asset = bundle(tmp_path)
    archive.write_bytes(archive.read_bytes() + b"corrupt")
    root = tmp_path / "checkout"
    with pytest.raises(ValueError, match="mismatch"):
        restore.restore_asset(archive, asset, root)
    assert not root.exists()


def test_manifest_and_symlink_escape_are_rejected(tmp_path):
    archive, asset = bundle(tmp_path, "../outside.txt")
    with pytest.raises(ValueError, match="Unsafe"):
        restore.restore_asset(archive, asset, tmp_path / "checkout")
    archive, asset = bundle(tmp_path)
    root = tmp_path / "checkout"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        restore.restore_asset(archive, asset, root)
    assert not list(outside.iterdir())
