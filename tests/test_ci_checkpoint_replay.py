"""Harness failure/oracle checks, not substitutes for actual scientific replays."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci_checkpoint_replay.py"
SPEC = importlib.util.spec_from_file_location("ci_checkpoint_replay", SCRIPT)
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)


class CheckpointReplayTests(unittest.TestCase):
    def run_orchestration(self, first_failure=None):
        """Fake child results isolate sequencing and fail-closed receipt behavior."""
        attempts = []
        truth_reads = []
        actual_read = REPLAY.read_json

        def read_json(path):
            if Path(path).name == "truth.json":
                self.assertEqual(attempts, ["two-events.json", "known-time-minute.json"])
                truth_reads.append(str(path))
            return actual_read(path)

        def execute(command, cwd, log_path, env, timeout_s):
            Path(log_path).write_text("Harness control fixture; no scientific run.\n")
            if str(command[1]).endswith("make_synthetic_cases.py"):
                root = Path(command[1]).parent.parent / "data/synthetic"
                root.mkdir(parents=True)
                (root / "recording.wav").write_bytes(b"fixture")
                (root / "tracks.csv").write_text("fixture")
                config = {"audio": "recording.wav", "tracks": ["tracks.csv"], "events": []}
                for name in ("two-events.json", "known-time-minute.json"):
                    (root / name).write_text(json.dumps(config))
                (root / "truth.json").write_text(json.dumps({
                    "lat": 40, "lon": -100, "flight_ids": ["a", "b"]}))
                return {"returncode": 0}
            self.assertEqual(command[1:4], ["-m", "aircraft_geoloc.cli", "run"])
            name = Path(command[4]).name
            attempts.append(name)
            destination = Path(command[-1])
            destination.mkdir()
            if not (len(attempts) == 1 and first_failure == "missing_report"):
                (destination / "report.json").write_text(json.dumps({
                    "best": {"lat": 40, "lon": -100, "flight_ids": ["a", "b"]},
                    "implementation_sha256": ("wrong" if len(attempts) == 1 and first_failure == "wrong_code"
                                              else REPLAY.pipeline_source_digest(Path(env["PYTHONPATH"])))}))
            return {"returncode": 7 if len(attempts) == 1 and first_failure == "exit" else 0}

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            with patch.object(REPLAY, "runtime_record", return_value={}), \
                 patch.object(REPLAY, "execute", side_effect=execute), \
                 patch.object(REPLAY, "read_json", side_effect=read_json), \
                 patch.object(REPLAY, "evaluate_best", return_value={"passed": True}), \
                 redirect_stdout(io.StringIO()):
                code = REPLAY.main(["--output", str(output)])
            receipt = actual_read(output / "acceptance.json")
            self.assertEqual(len(truth_reads), 1)
            self.assertTrue(receipt["evaluation_truth_loaded_after_all_searches"])
            self.assertEqual(len(receipt["cases"]), 2)
            self.assertTrue(receipt["cases"][1]["passed"])
            self.assertFalse(receipt["automatic_upload_verified"])
            self.assertFalse(receipt["independent_real_accuracy_verified"])
            self.assertFalse(receipt["nationwide_search_verified"])
            return code, receipt

    def test_truth_is_opened_only_after_both_cli_cases(self):
        code, receipt = self.run_orchestration()
        self.assertEqual(code, 0)
        self.assertTrue(receipt["passed"])

    def test_failed_case_is_not_hidden_by_later_success(self):
        for failure in ("exit", "missing_report", "wrong_code"):
            with self.subTest(failure=failure):
                code, receipt = self.run_orchestration(failure)
                self.assertEqual(code, 1)
                self.assertFalse(receipt["passed"])
                self.assertFalse(receipt["cases"][0]["passed"])
                self.assertIn("error", receipt["cases"][0])

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "keep.txt"
            marker.write_text("keep")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                REPLAY.main(["--output", temporary])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(marker.read_text(), "keep")

    def test_oracle_requires_correct_flights_and_strict_distance_bound(self):
        best = {"lat": 40, "lon": -100, "flight_ids": ["wrong"]}
        truth = {"lat": 40, "lon": -100}
        for distance, flights, passed in ((1, ["right"], False), (99.9, ["wrong"], True), (100, ["wrong"], False)):
            with self.subTest(distance=distance, flights=flights):
                geod = SimpleNamespace(inv=lambda *args: (0, 0, distance))
                with patch.dict("sys.modules", {"pyproj": SimpleNamespace(Geod=lambda **kwargs: geod)}):
                    result = REPLAY.evaluate_best(best, truth, flights)
                self.assertEqual(result["passed"], passed)

    def test_nonfinite_best_candidate_cannot_pass(self):
        with patch.dict("sys.modules", {"pyproj": SimpleNamespace(Geod=object)}):
            with self.assertRaisesRegex(ValueError, "finite lat"):
                REPLAY.evaluate_best({"lat": float("nan"), "lon": -100}, {"lat": 40, "lon": -100})

    def test_cache_inventory_does_not_claim_every_tile_was_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cache.mkdir()
            for path in (root / "audio.wav", root / "tracks.csv", root / "geoid.tif",
                         cache / "tileList.txt", cache / "unrelated.tif"):
                path.write_bytes(b"fixture")
            config = root / "config.json"
            config.write_text(json.dumps({"audio": "audio.wav", "tracks": ["tracks.csv"],
                "events": [], "terrain": {"copernicus_cache": "cache", "geoid_raster": "geoid.tif"}}))
            names = {Path(item["path"]).name for item in REPLAY.config_inputs(config)}
            self.assertIn("tileList.txt", names)
            self.assertIn("geoid.tif", names)
            self.assertNotIn("unrelated.tif", names)


if __name__ == "__main__":
    unittest.main()
