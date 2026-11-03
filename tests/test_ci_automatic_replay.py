"""Stdlib control checks only; no scientific stages or locations are mocked."""
from contextlib import redirect_stderr
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci_automatic_replay.py"
SPEC = importlib.util.spec_from_file_location("ci_automatic_replay", SCRIPT)
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)


class AutomaticReplayTests(unittest.TestCase):
    def result(self, status="succeeded"):
        return {"status": status,
                "coverage": {"search_complete": True, "data_status": "available"},
                "events": [{"event_id": "first", "harmonic_group_id": "one"},
                           {"event_id": "second", "harmonic_group_id": "two"}],
                "candidates": [{"event_ids": ["first", "second"]}]}

    def test_normal_request_contains_no_manual_scientific_hints(self):
        request = REPLAY.normal_request("recording.mp3")
        self.assertEqual(set(request), {"schema_version", "audio_path", "search", "time_window"})
        self.assertEqual(request["search"], {"coverage": "conus"})
        self.assertEqual(request["time_window"]["start_utc"], "2026-09-21T14:13:20Z")
        self.assertEqual(request["time_window"]["start_utc"], request["time_window"]["end_utc"])
        self.assertTrue(Path(request["audio_path"]).is_absolute())
        self.assertTrue(REPLAY.verify_normal_request(request, "recording.mp3"))
        for name, value in (("events", []), ("flight_ids", ["selected"]), ("true_lat", 40)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                REPLAY.verify_normal_request(dict(request, **{name: value}), "recording.mp3")

    def test_operator_uses_observed_absolute_keys_without_guessed_budget(self):
        operator = REPLAY.operator_configuration("index.sqlite")
        self.assertTrue(Path(operator["flight_indexes"][0]).is_absolute())
        self.assertTrue(operator["offline"])
        self.assertEqual(operator["terrain"], {"constant_m": 120})
        self.assertNotIn("search_budget", operator)
        self.assertNotIn("events", operator)
        self.assertNotIn("flight_ids", operator)

    def test_synthetic_source_envelope_covers_published_acoustic_margin(self):
        coverage = REPLAY.synthetic_coverage()
        self.assertTrue(coverage["synthetic"])
        self.assertTrue(coverage["all_aircraft"])
        self.assertIn("not real receiver coverage", coverage["source_note"])
        bounds = REPLAY.SYNTHETIC_BOUNDS
        radius = REPLAY.operator_configuration("index.sqlite")["max_distance_m"]
        angular = (1.6 * radius + 15000) / 110000
        longitude = angular / math.cos(math.radians(max(abs(bounds[1]), abs(bounds[3]))))
        required = [bounds[0] - longitude, bounds[1] - angular, bounds[2] + longitude, bounds[3] + angular]
        self.assertLessEqual(coverage["bounds"][0], required[0])
        self.assertLessEqual(coverage["bounds"][1], required[1])
        self.assertGreaterEqual(coverage["bounds"][2], required[2])
        self.assertGreaterEqual(coverage["bounds"][3], required[3])
        self.assertEqual(REPLAY.normal_request("audio.mp3")["search"], {"coverage": "conus"})

    def test_close_inconclusive_candidate_never_passes(self):
        evaluation = [{"meets_threshold": True, "distinct_flights_correct": True}]
        for status in ("inconclusive", "failed", "needs_input", "cancelled", "running"):
            with self.subTest(status=status):
                outcome = REPLAY.assess_outcome(self.result(status), evaluation, {"verified": True}, {"returncode": 0})
                self.assertTrue(outcome["top_candidate_within_100m"])
                self.assertFalse(outcome["supported_decision"])
                self.assertFalse(outcome["passed"])

    def test_forced_cli_exit_never_authorizes_reading_evaluation_truth(self):
        for status in ("succeeded", "inconclusive", "failed", "needs_input", "cancelled"):
            self.assertTrue(REPLAY.ready_for_evaluation({"status": status}, {"returncode": 0}))
            self.assertFalse(REPLAY.ready_for_evaluation({"status": status}, {"returncode": 1}))
            self.assertFalse(REPLAY.ready_for_evaluation({"status": status}, {"returncode": 0, "timed_out": True}))
        self.assertFalse(REPLAY.ready_for_evaluation({"status": "running"}, {"returncode": 0}))

    def test_supported_decision_still_requires_error_flights_coverage_and_provenance(self):
        good = [{"meets_threshold": True, "distinct_flights_correct": True}]
        self.assertTrue(REPLAY.assess_outcome(self.result(), good, {"verified": True}, {"returncode": 0})["passed"])
        for evaluations in ([], [{"meets_threshold": False, "distinct_flights_correct": True}],
                            [{"meets_threshold": True, "distinct_flights_correct": False}]):
            self.assertFalse(REPLAY.assess_outcome(self.result(), evaluations, {"verified": True}, {"returncode": 0})["passed"])
        for checks in ({}, {"verified": False}, {"verified": "yes"}):
            self.assertFalse(REPLAY.assess_outcome(self.result(), good, checks, {"returncode": 0})["passed"])
        for execution in ({"returncode": 1}, {"returncode": 0, "timed_out": True}):
            self.assertFalse(REPLAY.assess_outcome(self.result(), good, {"verified": True}, execution)["passed"])
        partial = self.result()
        partial["coverage"]["data_status"] = "partial"
        self.assertFalse(REPLAY.assess_outcome(partial, good, {"verified": True}, {"returncode": 0})["passed"])
        incomplete = self.result()
        incomplete["coverage"]["search_complete"] = False
        self.assertFalse(REPLAY.assess_outcome(incomplete, good, {"verified": True}, {"returncode": 0})["passed"])

    def test_duplicate_harmonics_do_not_supply_two_independent_events(self):
        result = self.result()
        result["events"][1]["harmonic_group_id"] = "one"
        outcome = REPLAY.assess_outcome(result, [{"meets_threshold": True, "distinct_flights_correct": True}],
                                        {"verified": True}, {"returncode": 0})
        self.assertEqual(outcome["independent_event_groups"], 1)
        self.assertFalse(outcome["passed"])

    def test_unmatched_discoveries_do_not_inflate_independent_event_count(self):
        result = self.result()
        result["candidates"][0]["event_ids"] = ["first"]
        outcome = REPLAY.assess_outcome(result, [{"meets_threshold": True, "distinct_flights_correct": True}],
                                        {"verified": True}, {"returncode": 0})
        self.assertEqual(outcome["independent_event_groups"], 1)
        self.assertFalse(outcome["passed"])
        for identifiers in (["first", "missing"], ["first", "first"], []):
            result["candidates"][0]["event_ids"] = identifiers
            outcome = REPLAY.assess_outcome(result, [{"meets_threshold": True, "distinct_flights_correct": True}],
                                            {"verified": True}, {"returncode": 0})
            self.assertFalse(outcome["matched_event_ids_valid"])
            self.assertFalse(outcome["passed"])

    def test_semantic_labels_are_removed_without_changing_any_trajectory_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluation = root / "evaluation"
            evaluation.mkdir()
            source, target = evaluation / "labeled-tracks.csv", root / "tracks.csv"
            mapping_path = evaluation / "flight-id-mapping.json"
            fields = ["flight_id", "time_s", "lat", "lon", "alt_m", "typecode"]
            identifiers = ["true-A", "true-B", "false1-A", "false1-B", "false2-A", "false2-B", "known-jet"]
            original_rows = [{"flight_id": identifier, "time_s": str(REPLAY.RECORDING_EPOCH + j),
                     "lat": str(40 + i / 100), "lon": "-100", "alt_m": str(1500 + j),
                     "typecode": "A320" if i == 6 else "C172"}
                    for i, identifier in enumerate(identifiers) for j in range(3)]
            with source.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(original_rows)
            # Truth is not needed by the transformation; unreadable JSON is fine.
            (evaluation / "truth.json").write_text("not a JSON document")
            inventory = REPLAY.anonymize_trajectories(source, target, mapping_path)
            mapping_record = json.loads(mapping_path.read_text())
            mapping = mapping_record["original_to_opaque"]
            self.assertEqual(set(mapping), set(identifiers))
            self.assertEqual(len(set(mapping.values())), 7)
            for identifier in identifiers:
                self.assertNotIn(identifier, target.read_text())
            with target.open(newline="") as stream:
                actual_rows = list(csv.DictReader(stream))
            expected_rows = [dict(row, flight_id=mapping[row["flight_id"]]) for row in original_rows]
            key = lambda row: (row["flight_id"], row["time_s"])
            self.assertEqual(sorted(actual_rows, key=key), sorted(expected_rows, key=key))
            self.assertEqual(inventory["rows"], 21)
            self.assertEqual(inventory["flight_count"], 7)
            self.assertEqual(inventory["typecode_rows"]["A320"], 3)
            self.assertEqual(REPLAY.evaluation_flight_ids({"flight_ids": ["true-A", "true-B"]}, mapping_record),
                             [mapping["true-A"], mapping["true-B"]])
            with self.assertRaises(KeyError):
                REPLAY.evaluation_flight_ids({"flight_ids": ["not-a-generated-flight"]}, mapping_record)

    def test_stage_artifact_presence_does_not_replace_consistency_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "search").mkdir()
            result = self.result()
            decision = {key: result[key] for key in ("status", "candidates")}
            search = {"status": "complete", "run_hash": "recorded-run", "tiles_total": 20,
                      "tiles_completed": 20, "unsearched_tiles": 0, "tile_failures": [],
                      "refinement_failure": None, "data_scope_complete": True,
                      "scope": list(REPLAY.SYNTHETIC_BOUNDS)}
            provenance = {"search_run_hash": "recorded-run"}
            def write():
                REPLAY.write_json(root / "decision.json", decision)
                REPLAY.write_json(root / "search/search-report.json", search)
            write()
            self.assertTrue(all(REPLAY.stage_consistency(root, result, provenance).values()))
            decision["status"] = "inconclusive"
            write()
            self.assertFalse(REPLAY.stage_consistency(root, result, provenance)["decision_artifact_consistent"])
            decision["status"] = "succeeded"
            search["tiles_completed"] = 19
            write()
            self.assertFalse(REPLAY.stage_consistency(root, result, provenance)["search_artifact_consistent"])
            search["tiles_completed"] = 20
            search["data_scope_complete"] = False
            write()
            self.assertFalse(REPLAY.stage_consistency(root, result, provenance)["search_artifact_consistent"])

    def test_supported_decision_cannot_override_explicit_unassessed_alternatives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "search").mkdir()
            result = self.result()
            decision = {key: result[key] for key in ("status", "candidates")}
            search = {"status": "complete", "run_hash": "recorded-run", "tiles_total": 20,
                      "tiles_completed": 20, "unsearched_tiles": 0, "tile_failures": [],
                      "refinement_failure": None, "data_scope_complete": True,
                      "scope": list(REPLAY.SYNTHETIC_BOUNDS),
                      "alternative_modes_exhaustively_assessed": False}
            provenance = {"search_run_hash": "recorded-run"}
            REPLAY.write_json(root / "decision.json", decision)
            REPLAY.write_json(root / "search/search-report.json", search)
            checks = REPLAY.stage_consistency(root, result, provenance)
            self.assertTrue(checks["decision_artifact_consistent"])
            self.assertTrue(checks["search_artifact_consistent"])
            self.assertFalse(checks["alternative_mode_evidence_consistent"])
            outcome = REPLAY.assess_outcome(result,
                [{"meets_threshold": True, "distinct_flights_correct": True}], checks, {"returncode": 0})
            self.assertTrue(outcome["supported_decision"])
            self.assertTrue(outcome["top_candidate_within_100m"])
            self.assertFalse(outcome["passed"])
            # This guard rejects the explicit contradiction; it does not invent
            # a replacement scientific threshold or completeness declaration.
            search["alternative_modes_exhaustively_assessed"] = True
            REPLAY.write_json(root / "search/search-report.json", search)
            self.assertTrue(REPLAY.stage_consistency(root, result, provenance)["alternative_mode_evidence_consistent"])
            search["alternative_modes_exhaustively_assessed"] = False
            result["status"] = decision["status"] = "inconclusive"
            REPLAY.write_json(root / "decision.json", decision)
            REPLAY.write_json(root / "search/search-report.json", search)
            self.assertTrue(REPLAY.stage_consistency(root, result, provenance)["alternative_mode_evidence_consistent"])

    def test_inventory_keeps_all_seven_aircraft_and_every_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracks.csv"
            fields = ["flight_id", "time_s", "lat", "lon", "alt_m", "typecode"]
            rows = [{"flight_id": f"aircraft-{i}", "time_s": REPLAY.RECORDING_EPOCH + j,
                     "lat": 40, "lon": -100, "alt_m": 1500, "typecode": "A320" if i == 6 else "C172"}
                    for i in range(7) for j in range(3)]
            def write(values):
                with path.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(values)
            write(rows)
            inventory = REPLAY.trajectory_inventory(path)
            self.assertEqual(inventory["flight_count"], 7)
            self.assertEqual(inventory["rows"], 21)
            self.assertEqual(inventory["typecode_rows"]["A320"], 3)
            write(rows[:-3])
            with self.assertRaisesRegex(ValueError, "all 7"):
                REPLAY.trajectory_inventory(path)

    def test_missing_producers_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "src/aircraft_geoloc"
            package.mkdir(parents=True)
            for name in REPLAY.REQUIRED_MODULES:
                if name not in {"tiled_search", "confidence"}:
                    (package / f"{name}.py").write_text("# Presence-only control fixture\n")
            with self.assertRaisesRegex(RuntimeError, "tiled_search, confidence"):
                REPLAY.require_components(directory)

    def test_failed_preparation_inventory_never_opens_evaluation_truth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evaluation").mkdir()
            # Invalid text still must not be opened or hashed in failure receipts.
            (root / "evaluation/truth.json").write_bytes(b"evaluation bytes")
            (root / "recording.mp3").write_bytes(b"input bytes")
            names = REPLAY.artifact_inventory(root, truth_loaded=False)
            self.assertEqual(set(names), {"recording.mp3"})
            names = REPLAY.artifact_inventory(root, truth_loaded=True)
            self.assertIn("evaluation/truth.json", names)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "preserve.txt"
            marker.write_text("unchanged")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                REPLAY.main(["--output", directory])
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(marker.read_text(), "unchanged")

    def test_status_observer_retains_actual_final_state_without_scientific_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "jobs/job").mkdir(parents=True)
            (root / "jobs/job/result.json").write_text(json.dumps({
                "job_id": "job", "status": "inconclusive", "stage": "complete",
                "reason_code": "no_supported_events"}))
            stopped = threading.Event()
            stopped.set()
            warnings = []
            target = root / "history.jsonl"
            REPLAY.observe_job_states(root / "jobs", target, stopped, warnings)
            records = [json.loads(line) for line in target.read_text().splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["state"]["status"], "inconclusive")
            self.assertEqual(records[0]["state"]["reason_code"], "no_supported_events")
            self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
