"""Offline checks of release restoration; no public download is required."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/restore_ci_checkpoint.py"
SPEC = importlib.util.spec_from_file_location("restore_ci_checkpoint", SCRIPT)
RESTORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESTORE)


class CheckpointRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.destination = self.root / "checkout"
        self.destination.mkdir()
        self.archive = self.root / "fixture.tar.gz"
        self.files = {"data/source/input.txt": b"reference fixture\n",
                      "data/source/settings.json": b"{}\n"}
        with tarfile.open(self.archive, "w:gz") as bundle:
            for name, content in self.files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
        self.asset = {"bytes": self.archive.stat().st_size,
                      "sha256": RESTORE.digest(self.archive),
                      "files": [{"path": name, "bytes": len(content),
                                 "sha256": hashlib.sha256(content).hexdigest()}
                                for name, content in self.files.items()]}

    def test_verified_contents_restored_and_second_run_preserves_files(self):
        self.assertEqual(RESTORE.restore_archive(self.archive, self.asset, self.destination), 2)
        for name, content in self.files.items():
            self.assertEqual((self.destination / name).read_bytes(), content)
        target = self.destination / "data/source/input.txt"
        target.write_bytes(b"independent evidence")
        with self.assertRaises(FileExistsError):
            RESTORE.restore_archive(self.archive, self.asset, self.destination)
        self.assertEqual(target.read_bytes(), b"independent evidence")

    def test_member_checksum_failure_writes_no_destination_files(self):
        self.asset["files"][-1]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Checksum or size mismatch"):
            RESTORE.restore_archive(self.archive, self.asset, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_manifest_missing_member_is_rejected_before_writes(self):
        self.asset["files"].append({"path": "data/source/missing.txt", "bytes": 0,
                                    "sha256": hashlib.sha256(b"").hexdigest()})
        with self.assertRaisesRegex(ValueError, "Missing manifest files"):
            RESTORE.restore_archive(self.archive, self.asset, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
