"""Harness failure/oracle checks, not substitutes for actual scientific replays."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci_checkpoint_replay.py"
SPEC = importlib.util.spec_from_file_location("ci_checkpoint_replay", SCRIPT)
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)


class CheckpointReplayTests(unittest.TestCase):
    def test_rss_rejects_namespace_mismatch_before_reading_numeric_proc_paths(self):
        with patch.object(REPLAY.sys, "platform", "linux"), \
             patch.object(REPLAY.os, "getpid", return_value=1000), \
             patch.object(REPLAY.os, "readlink", return_value="9000"), \
             patch.object(REPLAY, "Path", side_effect=AssertionError("Unrelated process must not be sampled")) as paths:
            self.assertEqual(REPLAY.rss_measurement_unavailable_reason(), "proc_pid_namespace_mismatch")
            self.assertIsNone(REPLAY.sampled_tree_rss(2000))
            paths.assert_not_called()

    def test_rss_rejects_unverified_proc_namespace(self):
        with patch.object(REPLAY.sys, "platform", "linux"), \
             patch.object(REPLAY.os, "readlink", side_effect=PermissionError("unavailable")), \
             patch.object(REPLAY, "Path") as paths:
            self.assertEqual(REPLAY.rss_measurement_unavailable_reason(), "proc_pid_namespace_unverified")
            self.assertIsNone(REPLAY.sampled_tree_rss(2000))
            paths.assert_not_called()

    def test_execute_records_unavailable_memory_without_sampling_unrelated_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "execution.log"
            with patch.object(REPLAY, "rss_measurement_unavailable_reason", return_value="proc_pid_namespace_mismatch"), \
                 patch.object(REPLAY, "sampled_tree_rss") as sampler:
                result = REPLAY.execute([sys.executable, "-c", "print('completed')"],
                                        temporary, log, os.environ.copy(), 5)
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(log.read_text().strip(), "completed")
            self.assertIsNone(result["peak_sampled_process_tree_rss_bytes"])
            self.assertEqual(result["memory_measurement_status"], "unavailable")
            self.assertEqual(result["memory_measurement_reason"], "proc_pid_namespace_mismatch")
            sampler.assert_not_called()

    def test_missing_or_zero_rss_is_not_reported_as_measured_zero_memory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            zero = root / "1000"
            zero.mkdir()
            (zero / "statm").write_text("0 0 0 0 0 0 0\n")
            (zero / "task").mkdir()
            def proc_path(value):
                return root / Path(value).relative_to("/proc")
            with patch.object(REPLAY, "Path", side_effect=proc_path), \
                 patch.object(REPLAY, "rss_measurement_unavailable_reason", return_value=None):
                self.assertIsNone(REPLAY.sampled_tree_rss(1000))
                self.assertIsNone(REPLAY.sampled_tree_rss(2000))
            with patch.object(REPLAY, "rss_measurement_unavailable_reason", return_value=None), \
                 patch.object(REPLAY, "sampled_tree_rss", return_value=None):
                result = REPLAY.execute([sys.executable, "-c", "pass"], temporary,
                                        root / "execution.log", os.environ.copy(), 5)
            self.assertIsNone(result["peak_sampled_process_tree_rss_bytes"])
            self.assertEqual(result["memory_measurement_status"], "unavailable")
            self.assertEqual(result["memory_measurement_reason"], "no_valid_rss_samples")

    def test_rss_visits_all_thread_children_and_counts_each_process_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def process(pid, resident_pages, threads):
                directory = root / str(pid)
                directory.mkdir()
                (directory / "statm").write_text(f"100 {resident_pages} 0 0 0 0 0\n")
                for tid, children in threads.items():
                    task = directory / "task" / str(tid)
                    task.mkdir(parents=True)
                    if children is not None:
                        (task / "children").write_text(children)
            # A disappearing task/process and a duplicate observed PID must not
            # hide siblings or count the same process more than once.
            process(1000, 3, {1000: "2000 9000", 1001: None, 1002: "3000 2000"})
            process(2000, 5, {2000: "", 2001: "4000"})
            process(3000, 7, {3000: ""})
            process(4000, 11, {4000: ""})
            def proc_path(value):
                return root / Path(value).relative_to("/proc")
            with patch.object(REPLAY, "Path", side_effect=proc_path), \
                 patch.object(REPLAY.sys, "platform", "linux"), \
                 patch.object(REPLAY.os, "getpid", return_value=1000), \
                 patch.object(REPLAY.os, "readlink", return_value="1000"):
                actual = REPLAY.sampled_tree_rss(1000)
            self.assertEqual(actual, (3 + 5 + 7 + 11) * os.sysconf("SC_PAGE_SIZE"))

    @unittest.skipUnless(sys.platform == "linux", "Requires Linux /proc")
    def test_rss_includes_child_spawned_by_background_thread(self):
        reason = REPLAY.rss_measurement_unavailable_reason()
        if reason is not None:
            self.skipTest(f"Live process-tree RSS is unavailable: {reason}")
        if not Path("/proc/thread-self/children").is_file():
            self.skipTest("Requires Linux per-thread /proc children interfaces")
        child_program = """import time
memory = bytearray(64 * 1024 * 1024)
for offset in range(0, len(memory), 4096):
    memory[offset] = 1
print('ready', flush=True)
time.sleep(30)
"""
        controller_program = textwrap.dedent(f"""
            import json, subprocess, sys, threading
            stop = threading.Event()
            def worker():
                child = subprocess.Popen([sys.executable, '-c', {child_program!r}],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
                try:
                    assert child.stdout.readline().strip() == 'ready'
                    print(json.dumps({{'child_pid': child.pid, 'thread_id': threading.get_native_id()}}), flush=True)
                    stop.wait(20)
                finally:
                    child.terminate()
                    child.wait(timeout=5)
                    child.stdout.close()
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                sys.stdin.read(1)
            finally:
                stop.set()
                thread.join()
        """)
        controller = subprocess.Popen([sys.executable, "-c", controller_program],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(controller.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=10), "Threaded child did not become ready")
                identity = json.loads(controller.stdout.readline())
            parent, child, thread = controller.pid, identity["child_pid"], identity["thread_id"]
            leader_children = Path(f"/proc/{parent}/task/{parent}/children").read_text().split()
            worker_children = Path(f"/proc/{parent}/task/{thread}/children").read_text().split()
            self.assertNotIn(str(child), leader_children)
            self.assertIn(str(child), worker_children)
            child_rss = REPLAY.sampled_tree_rss(child)
            self.assertGreater(child_rss, 48 * 1024 * 1024)
            self.assertGreaterEqual(REPLAY.sampled_tree_rss(parent), child_rss)
        finally:
            try:
                controller.communicate(input="\n", timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(controller.pid, signal.SIGKILL)
                controller.communicate(timeout=5)

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
                "events": [], "terrain": {"copernicus_cache": "cache", "geoid_raster": "geoid.tif",
                                           "rasters": ["inactive-and-absent.tif"]}}))
            names = {Path(item["path"]).name for item in REPLAY.config_inputs(config)}
            self.assertIn("tileList.txt", names)
            self.assertIn("geoid.tif", names)
            self.assertNotIn("unrelated.tif", names)
            self.assertNotIn("inactive-and-absent.tif", names)


if __name__ == "__main__":
    unittest.main()
