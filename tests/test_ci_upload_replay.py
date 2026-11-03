"""Fail-closed controls for the upload wrapper; no scientific run is simulated."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location("ci_upload_replay",
    Path(__file__).parents[1] / "scripts/ci_upload_replay.py")
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)
CLOCK = "2026-09-21T14:13:20Z"


def complete_checks():
    return {name: True for name in REPLAY.REQUIRED_CHECKS}


def scene(status="succeeded"):
    events, labels, mapping = [], [], {}
    for index in range(4):
        event, old, flight = f"e{index}", f"label{index}", f"opaque{index}"
        center = 100 + 220 * index
        events.append({"event_id": event, "harmonic_group_id": f"group{index}",
                       "start_s": center - 20, "end_s": center + 20,
                       "ridge": [{"time_s": center + offset, "frequency_hz": 135 + 23 * index}
                                 for offset in (-2, -1, 0, 1, 2)]})
        labels.append({"flight_id": old, "start_s": center - 20, "end_s": center + 20})
        mapping[old] = flight
    candidate = {"lat": 40, "lon": -100, "score": -0.5, "recording_start_utc": CLOCK,
                 "event_ids": [event["event_id"] for event in events],
                 "flight_ids": list(mapping.values())}
    result = {"status": status, "events": events, "candidates": [candidate],
              "coverage": {"search_complete": True, "data_status": "available"}}
    return result, {"location": [40, -100], "events": labels, "recording_start_utc": CLOCK}, mapping


def lifecycle(**changes):
    server = {"shutdown_signal": "SIGINT", "returncode": 0, "forced_kill": False, "stopped_utc": "after"}
    server.update(changes)
    return {"servers": [server]}


def evaluate(result, labels, mapping, error=10):
    return REPLAY.evaluate_candidates(result, labels, mapping, lambda *args: error, tolerance_s=1,
                                      request_window={"start_utc": CLOCK, "end_utc": CLOCK})


def recorded_fit(result):
    candidate = result["candidates"][0]
    diagnostics = [{"score": -0.5, "rmse_hz": 0.1, "sample_count": 5,
                    "independent_sample_count": 5, "support_fraction": 1} for _ in range(4)]
    profiles = [{"source": "frequency", "scenario": f"event_{i}_{pattern}_{sign:+d}", "optimizer_success": True}
                for i in range(4) for pattern in ("offset", "tilt") for sign in (-1, 1)]
    profiles += [{"source": "altitude", "flight_altitude_bias": {"flight_id": flight, "bias_m": sign * 150}}
                 for flight in candidate["flight_ids"] for sign in (-1, 1)]
    row = dict(candidate, recording_start_time_s=1790000000, event_indices=list(range(4)),
               event_diagnostics=diagnostics, sensitivity={"profiles": profiles,
               "settings": {"frequency_scale_hz": [1] * 4, "altitude_uncertainty_m": 150}})
    return {"ranked": [row], "matching_diagnostics": dict(zip(candidate["event_ids"], diagnostics))}


class UploadReplayControls(unittest.TestCase):
    def test_explicit_event_cap_is_partial_despite_completed_tile_work(self):
        search = {"tiles_total": 10, "tiles_completed": 10, "unsearched_tiles": 0,
                  "tile_failures": [], "refinement_failure": None, "data_scope_complete": True,
                  "all_event_groups_considered": False, "status": "partial", "scope": REPLAY.SCOPE,
                  "run_hash": "recorded"}
        coverage = {"search_complete": True, "data_status": "available"}
        self.assertTrue(REPLAY.search_matches_result(search, coverage, {"search_run_hash": "recorded"}))
        result, labels, mapping = scene()
        checks = dict(complete_checks(), all_event_groups_considered=False)
        self.assertFalse(REPLAY.assess(result, evaluate(result, labels, mapping), checks, True, True, 4)["passed"])

    def test_nominal_binding_uses_actual_prepared_order_and_all_diagnostics(self):
        result, _, _ = scene()
        result["events"].reverse()
        artifact = recorded_fit(result)
        readout = REPLAY.reported_fit_profile(result, artifact)
        self.assertTrue(readout["leading_row_bound"])
        self.assertTrue(readout["nominal_diagnostics_complete"])
        artifact["ranked"][0]["event_diagnostics"].pop()
        self.assertFalse(REPLAY.reported_fit_profile(result, artifact)["nominal_diagnostics_complete"])
        artifact["ranked"][0]["score"] = 99
        self.assertFalse(REPLAY.reported_fit_profile(result, artifact)["leading_row_bound"])

    def test_missing_profile_scenario_is_reported_without_new_uncertainty_policy(self):
        result, _, _ = scene()
        artifact = recorded_fit(result)
        profiles = artifact["ranked"][0]["sensitivity"]["profiles"]
        profiles[:] = [row for row in profiles if row.get("scenario") != "event_3_tilt_+1"]
        readout = REPLAY.reported_fit_profile(result, artifact)
        profile = readout["reported_profile_participation"]
        self.assertTrue(readout["nominal_diagnostics_complete"])
        self.assertFalse(profile["frequency_by_event"][3]["all_declared_scenarios_recorded"])
        self.assertTrue(all(row["both_declared_signs_recorded"] for row in profile["altitude_by_flight"]))
        self.assertFalse(profile["used_as_additional_uncertainty_acceptance_policy"])
        self.assertFalse(readout["empirical_leave_one_out_effect_tested"])

    def test_reported_clock_outside_exact_request_window_cannot_pass(self):
        result, labels, mapping = scene()
        result["candidates"][0]["recording_start_utc"] = "2026-09-21T14:13:20.001Z"
        rows = evaluate(result, labels, mapping)
        self.assertEqual(rows[0]["clock"]["clock_error_s"], 0.001)
        self.assertFalse(rows[0]["clock"]["within_request_window"])
        self.assertFalse(REPLAY.assess(result, rows, complete_checks(), True, True, 4)["passed"])
        del result["candidates"][0]["recording_start_utc"]
        self.assertFalse(evaluate(result, labels, mapping)[0]["clock"]["within_request_window"])

    def test_completed_tile_work_can_have_partial_source_coverage(self):
        search = {"tiles_total": 10, "tiles_completed": 10, "unsearched_tiles": 0,
                  "tile_failures": [], "refinement_failure": None, "data_scope_complete": False,
                  "status": "partial", "scope": REPLAY.SCOPE, "run_hash": "recorded"}
        coverage = {"search_complete": True, "data_status": "partial"}
        self.assertTrue(REPLAY.search_matches_result(search, coverage, {"search_run_hash": "recorded"}))
        self.assertFalse(REPLAY.search_matches_result(dict(search, status="complete"), coverage,
                                                      {"search_run_hash": "recorded"}))

    def test_normal_request_rejects_scientific_hints(self):
        request = {"schema_version": 1, "audio_path": "recording.mp3", "search": {"coverage": "conus"},
                   "time_window": {"start_utc": "2026-09-21T14:13:20Z", "end_utc": "2026-09-21T14:13:20Z", "source": "user"}}
        wire = REPLAY.normal_wire_request(request)
        self.assertNotIn("audio_path", wire)
        self.assertEqual(wire["time_window"]["source_detail"], REPLAY.TIME_SOURCE)
        for name in ("events", "flight_ids", "location"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                REPLAY.normal_wire_request(dict(request, **{name: []}))

    def test_shutdown_adapter_signals_only_server_and_records_wait(self):
        process = Mock(pid=123)
        process.wait.return_value = 0
        record = {"forced_kill": False}
        save = Mock()
        managed = REPLAY.ManagedServer(process, record, save)
        managed.terminate()
        process.send_signal.assert_called_once_with(signal.SIGINT)
        process.terminate.assert_not_called()
        self.assertEqual(managed.wait(timeout=10), 0)
        self.assertEqual(record["shutdown_signal"], "SIGINT")
        self.assertEqual(record["returncode"], 0)
        self.assertTrue(record["stopped_utc"])
        managed.kill()
        self.assertTrue(record["forced_kill"])

    def test_proxy_refuses_nonserver_popen(self):
        with tempfile.TemporaryDirectory() as temporary:
            proxy = REPLAY.VerifierSubprocess(Path(temporary) / "lifecycle.json")
            with patch.object(REPLAY.subprocess, "Popen") as process, self.assertRaises(ValueError):
                proxy.Popen(["python", "unreviewed.py"])
            process.assert_not_called()

    def test_browser_failure_does_not_prevent_safe_diagnostics(self):
        self.assertTrue(REPLAY.ready_for_truth({"status": "inconclusive"},
            {"returncode": 1, "timed_out": False}, lifecycle()))
        for changed in ({"forced_kill": True}, {"returncode": -9}, {"shutdown_signal": "SIGTERM"}):
            with self.subTest(changed=changed):
                self.assertFalse(REPLAY.ready_for_truth({"status": "inconclusive"},
                    {"returncode": 1, "timed_out": False}, lifecycle(**changed)))
        self.assertFalse(REPLAY.ready_for_truth({"status": "inconclusive"}, {"timed_out": True}, lifecycle()))
        self.assertFalse(REPLAY.ready_for_truth({"status": "running"}, {}, lifecycle()))

    def test_expected_inconclusive_is_never_supported(self):
        result, labels, mapping = scene("inconclusive")
        outcome = REPLAY.assess(result, evaluate(result, labels, mapping),
            complete_checks(), True, True, 4)
        self.assertTrue(outcome["transport_ui_passed"])
        self.assertFalse(outcome["supported_localization_passed"])
        self.assertFalse(outcome["passed"])

    def test_four_true_flyovers_and_timing_can_pass_at_declared_threshold(self):
        result, labels, mapping = scene()
        evaluations = evaluate(result, labels, mapping, 1000)
        outcome = REPLAY.assess(result, evaluations, complete_checks(), True, True, 4)
        self.assertTrue(outcome["passed"])
        self.assertEqual(outcome["supported_localization_at_m"], {"100": False, "500": False, "1000": True})
        self.assertTrue(evaluations[0]["association_timing"]["compatible"])

    def test_cross_event_assignment_fails_despite_correct_flight_set(self):
        result, labels, mapping = scene()
        result["candidates"][0]["flight_ids"] = list(reversed(result["candidates"][0]["flight_ids"]))
        evaluations = evaluate(result, labels, mapping)
        self.assertTrue(evaluations[0]["full_true_flight_set_correct"])
        self.assertFalse(evaluations[0]["association_timing"]["compatible"])
        self.assertFalse(REPLAY.assess(result, evaluations, complete_checks(), True, True, 4)["passed"])

    def test_duplicate_groups_and_missing_true_flyovers_fail(self):
        for defect in ("duplicate_event", "shared_group", "missing_flight"):
            result, labels, mapping = scene()
            candidate = result["candidates"][0]
            if defect == "duplicate_event":
                candidate["event_ids"][1] = candidate["event_ids"][0]
            elif defect == "shared_group":
                result["events"][1]["harmonic_group_id"] = result["events"][0]["harmonic_group_id"]
            else:
                candidate["flight_ids"][1] = candidate["flight_ids"][0]
            with self.subTest(defect=defect):
                self.assertFalse(REPLAY.assess(result, evaluate(result, labels, mapping),
                    complete_checks(), True, True, 4)["passed"])

    def test_two_groups_cannot_claim_four_flyovers(self):
        result, labels, mapping = scene()
        candidate = result["candidates"][0]
        candidate["event_ids"] = candidate["event_ids"][:2]
        candidate["flight_ids"] = candidate["flight_ids"][:2]
        outcome = REPLAY.assess(result, evaluate(result, labels, mapping),
            complete_checks(), True, True, 4)
        self.assertFalse(outcome["required_flyovers_explained"])
        self.assertFalse(outcome["passed"])

    def test_partial_artifact_checks_cannot_pass(self):
        result, labels, mapping = scene()
        rows = evaluate(result, labels, mapping)
        for checks in ({"one_true_check": True}, {"evidence_collection_complete": False, "one_true_check": True}):
            with self.subTest(checks=checks):
                self.assertFalse(REPLAY.assess(result, rows, checks, True, True, 4)["passed"])

    def test_better_lower_rank_never_replaces_leading_prediction(self):
        result, labels, mapping = scene()
        rows = evaluate(result, labels, mapping, 2000) + evaluate(result, labels, mapping, 1)
        outcome = REPLAY.assess(result, rows, complete_checks(), True, True, 4)
        self.assertEqual(outcome["leading_prediction_error_m"], 2000)
        self.assertFalse(outcome["passed"])

    def test_browser_failure_is_separate_from_supported_location(self):
        result, labels, mapping = scene()
        outcome = REPLAY.assess(result, evaluate(result, labels, mapping),
            complete_checks(), False, True, 4)
        self.assertTrue(outcome["supported_localization_passed"])
        self.assertFalse(outcome["transport_ui_passed"])
        self.assertFalse(outcome["passed"])

    def test_missing_actual_window_and_nonfinite_candidates_fail(self):
        result, labels, mapping = scene()
        rows = REPLAY.evaluate_candidates(result, labels, mapping, lambda *args: 1)
        self.assertFalse(rows[0]["association_timing"]["compatible"])
        result["candidates"].insert(0, dict(result["candidates"][0], lat=float("nan")))
        rows = evaluate(result, labels, mapping)
        self.assertIsNone(rows[0]["error_m"])
        self.assertIn("Invalid candidate", rows[0]["error"])
        self.assertEqual(rows[1]["error_m"], 10)


    def test_unproven_shutdown_never_opens_truth(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product, evaluation = root / "product", root / "evaluation"
            product.mkdir()
            (evaluation / "truth").mkdir(parents=True)
            (evaluation / "truth/labels.json").write_text("must never be parsed")
            REPLAY.write_json(product / "report.json", {"passed": False})
            REPLAY.write_json(root / "lifecycle.json", lifecycle(forced_kill=True))
            result, _, _ = scene("inconclusive")
            receipt = {"implementation": {"expected_implementation_files": {}}, "evaluation_truth_loaded": False}
            actual_read, seen = REPLAY.read_json, []
            def read(path):
                seen.append(Path(path).name)
                return actual_read(path)
            with patch.object(REPLAY, "collect_job", return_value=(result, {"checks": {}})), \
                 patch.object(REPLAY, "read_json", side_effect=read), self.assertRaisesRegex(RuntimeError, "labels remain unopened"):
                REPLAY.finish_evaluation(receipt, root, product, root / "lifecycle.json", root, evaluation,
                                         {}, {}, {"returncode": 1, "timed_out": False})
            self.assertNotIn("labels.json", seen)
            self.assertFalse(receipt["evaluation_truth_loaded"])

    def test_failure_manifest_excludes_all_evaluation_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "evaluation/truth").mkdir(parents=True)
            (root / "evaluation/truth/labels.json").write_text("not an input")
            (root / "evaluation/generation.json").write_text("contains a truth hash")
            (root / "input.mp3").write_bytes(b"input")
            receipt = {"evaluation_truth_loaded": False, "passed": False}
            REPLAY.write_json(root / "acceptance.json", receipt)
            with redirect_stdout(io.StringIO()):
                REPLAY.inventory_and_print(root, receipt)
            manifest = REPLAY.read_json(root / "artifact-manifest.json")
            self.assertEqual(set(manifest["files"]), {"input.mp3"})

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "keep.txt"
            marker.write_text("retained")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                REPLAY.main(["--output", temporary, "--browser-python", "/python", "--expect-status", "inconclusive"])
            self.assertEqual(marker.read_text(), "retained")


if __name__ == "__main__":
    unittest.main()
