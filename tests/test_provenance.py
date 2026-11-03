"""Stdlib-only regression checks, also collected by pytest."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from dopplergeist.provenance import RunProvenance, implementation_provenance


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config_path = self.root / "config.json"
        self.config = {
            "audio": "recording.wav", "tracks": ["tracks.csv", "tracks.csv"],
            "events": [{"ridge_csv": "ridge.csv"}, {}],
            "type_database": "types.csv",
            "terrain": {"rasters": ["ground.tif"], "geoid_raster": "geoid.tif"},
        }
        self.input_bytes = {
            "recording.wav": b"audio bytes", "tracks.csv": b"track bytes",
            "ridge.csv": b"time_s,frequency_hz\n0,100\n", "types.csv": b"types",
            "ground.tif": b"ground raster", "geoid.tif": b"geoid raster",
        }
        for name, data in self.input_bytes.items():
            (self.root / name).write_bytes(data)

    def recorder(self):
        raw = (json.dumps(self.config, indent=3) + "\n\n").encode()
        self.config_path.write_bytes(raw)
        return RunProvenance(self.config_path, raw), raw

    def test_all_declared_input_kinds_are_recorded_once_with_exact_config_bytes(self):
        recorder, raw = self.recorder()
        recorder.collect_declared_inputs(self.config)
        entries = {Path(row["path"]).name: row for row in recorder.sources}
        expected = dict(self.input_bytes, **{"config.json": raw})
        self.assertEqual(set(entries), set(expected))
        for name, data in expected.items():
            self.assertEqual(entries[name]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(entries["ridge.csv"]["roles"], ["ridge_csv"])
        self.assertEqual(entries["types.csv"]["roles"], ["type_database"])
        self.assertEqual(entries["ground.tif"]["roles"], ["terrain"])
        self.assertEqual(entries["geoid.tif"]["roles"], ["geoid"])
        self.assertEqual(recorder.declaration()["configuration_sha256"], hashlib.sha256(raw).hexdigest())
        json.dumps({"sources": recorder.sources, "provenance": recorder.declaration()}, allow_nan=False)

    def test_configuration_digest_is_not_replaced_by_a_later_file_read(self):
        recorder, raw = self.recorder()
        self.config_path.write_text('{"different": true}\n')
        recorder.collect_declared_inputs(self.config)
        config_entry = next(row for row in recorder.sources if "configuration" in row["roles"])
        self.assertEqual(config_entry["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(config_entry["captured_at"], "parsed_configuration")

    def test_resolved_duplicates_accumulate_roles_without_duplicate_entries(self):
        recorder, _ = self.recorder()
        (self.root / "subdir").mkdir()
        recorder.add_file(self.root / "tracks.csv", "tracks")
        recorder.add_file(self.root / "subdir/../tracks.csv", "another_role")
        entries = [row for row in recorder.sources if Path(row["path"]).name == "tracks.csv"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["roles"], ["another_role", "tracks"])
        entries[0]["roles"].append("external mutation")
        current = next(row for row in recorder.sources if Path(row["path"]).name == "tracks.csv")
        self.assertNotIn("external mutation", current["roles"])

    def test_changed_input_is_rejected_if_registered_again(self):
        recorder, _ = self.recorder()
        path = self.root / "tracks.csv"
        recorder.add_file(path, "tracks")
        path.write_bytes(b"changed track bytes")
        with self.assertRaisesRegex(ValueError, "Input changed"):
            recorder.add_file(path, "tracks")

    def test_missing_declared_file_is_not_silently_omitted(self):
        recorder, _ = self.recorder()
        (self.root / "ridge.csv").unlink()
        with self.assertRaises(FileNotFoundError):
            recorder.collect_declared_inputs(self.config)

    def test_missing_tile_usage_is_explicit_and_unused_cache_files_are_not_hashed(self):
        recorder, _ = self.recorder()
        cache = self.root / "tiles"
        cache.mkdir()
        (cache / "tileList.txt").write_text("used\nunused\n")
        (cache / "unused.tif").write_bytes(b"unrelated cached raster")
        recorder.collect_terrain_inputs({"copernicus_cache": "tiles"}, SimpleNamespace(cache=cache))
        names = {Path(row["path"]).name for row in recorder.sources}
        self.assertIn("tileList.txt", names)
        self.assertNotIn("unused.tif", names)
        self.assertTrue(any("tiles actually used" in text for text in recorder.declaration()["limitations"]))

    def test_exposed_used_tiles_are_hashed_without_inactive_rasters_or_cache_sweep(self):
        self.config["terrain"] = {"copernicus_cache": "tiles", "geoid_raster": "geoid.tif",
                                  "rasters": ["inactive-and-missing.tif"]}
        recorder, _ = self.recorder()
        cache = self.root / "tiles"
        cache.mkdir()
        (cache / "tileList.txt").write_text("used\nunused\n")
        used, unused = cache / "used.tif", cache / "unused.tif"
        used.write_bytes(b"used raster")
        unused.write_bytes(b"unused raster")
        recorder.collect_declared_inputs(self.config)
        recorder.collect_terrain_inputs(self.config["terrain"], SimpleNamespace(used_tile_paths=[used]))
        entries = {Path(row["path"]).name: row for row in recorder.sources}
        self.assertNotIn("unused.tif", entries)
        self.assertNotIn("inactive-and-missing.tif", entries)
        self.assertEqual(entries["used.tif"]["sha256"], hashlib.sha256(b"used raster").hexdigest())
        self.assertEqual(entries["used.tif"]["captured_at"], "after_terrain_sampling")
        self.assertEqual(entries["used.tif"]["roles"], ["terrain_tile"])

    def test_hashes_do_not_assert_truth_separation(self):
        recorder, _ = self.recorder()
        declaration = recorder.declaration()
        self.assertEqual(declaration["truth_separation"], "not_assessed")
        self.assertNotIn("ground_truth_used_by_search", declaration)
        self.assertTrue(any("ground truth" in text for text in declaration["limitations"]))

    def test_wheel_layout_excludes_unrelated_installed_packages(self):
        roots = [self.root / "checkout/src", self.root / "venv/lib/python/site-packages"]
        files = {"dopplergeist/__init__.py": b"version = 1\n",
                 "dopplergeist/web/__init__.py": b"assets = True\n"}
        for root in roots:
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        installed = roots[1]
        sibling = installed / "unrelated_package/module.py"
        sibling.parent.mkdir()
        sibling.write_bytes(b"external = 1\n")
        (installed / "unrelated.py").write_bytes(b"external = 2\n")
        checkout = implementation_provenance(roots[0])
        wheel = implementation_provenance(installed)
        self.assertEqual({row["relative_path"] for row in wheel["sources"]}, set(files))
        self.assertEqual(wheel["sha256"], checkout["sha256"])
        sibling.write_bytes(b"external = 3\n")
        self.assertEqual(implementation_provenance(installed)["sha256"], wheel["sha256"])
        (installed / "dopplergeist/web/__init__.py").write_bytes(b"assets = False\n")
        self.assertNotEqual(implementation_provenance(installed)["sha256"], wheel["sha256"])
        with self.assertRaises(FileNotFoundError):
            implementation_provenance(sibling.parent)

    def test_code_manifest_preserves_legacy_digest_and_detects_code_changes(self):
        root = self.root / "src"
        package = root / "dopplergeist"
        (package / "pkg").mkdir(parents=True)
        (package / "a.py").write_bytes(b"a = 1\n")
        (package / "pkg/b.py").write_bytes(b"b = 2\n")
        (root / "ignored.txt").write_bytes(b"not Python source")
        result = implementation_provenance(root)
        expected = hashlib.sha256(b"dopplergeist/a.py" + b"a = 1\n" +
                                  b"dopplergeist/pkg/b.py" + b"b = 2\n").hexdigest()
        self.assertEqual(result["sha256"], expected)
        self.assertEqual([row["relative_path"] for row in result["sources"]],
                         ["dopplergeist/a.py", "dopplergeist/pkg/b.py"])
        self.assertEqual(result["sources"][1]["sha256"], hashlib.sha256(b"b = 2\n").hexdigest())
        (package / "pkg/b.py").write_bytes(b"b = 3\n")
        self.assertNotEqual(implementation_provenance(root)["sha256"], expected)


if __name__ == "__main__":
    unittest.main()
