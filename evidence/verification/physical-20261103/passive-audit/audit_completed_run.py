"""Read-only audit of a completed automatic run; never opens evaluation truth.

This checks persisted evidence, not localization accuracy or calibration. It
does not call the detector, scorer, optimizer, decision rule or HTTP service.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess


def read(path):
    def reject(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")
    return json.loads(path.read_text(), parse_constant=reject)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def close(a, b):
    return math.isclose(a, b, abs_tol=1e-8, rel_tol=1e-10)


def audit(args):
    run = args.run.resolve(strict=True)
    if args.output.exists():
        raise FileExistsError("Preserve previous audit outputs")
    result = read(run / "result.json")
    if result["status"] in {"queued", "running"}:
        raise ValueError("Audit requires a terminal job result")
    names = ["result.json", "request.json", "operator.json", "provenance.json",
             "decision.json", "refined-candidates.json", "search/manifest.json",
             "search/search-report.json"]
    records = {name: read(run / name) for name in names}
    provenance = records["provenance.json"]
    manifest = records["search/manifest.json"]
    search = records["search/search-report.json"]
    refinement = records["refined-candidates.json"]
    decision = records["decision.json"]
    configuration = manifest["configuration"]
    checks = []

    def check(name, passed, **details):
        checks.append(dict(check=name, passed=bool(passed), **details))

    source_files = {}
    for name, expected in provenance["implementation_files"].items():
        blob = subprocess.check_output(["git", "show", args.source_commit + ":src/aircraft_geoloc/" + name], cwd=args.repo)
        actual = hashlib.sha256(blob).hexdigest()
        source_files[name] = dict(expected=expected, actual=actual, matches=expected == actual)
    check("source_files_match_declared_commit", all(r["matches"] for r in source_files.values()), files=source_files)
    check("search_and_orchestration_source_agree", configuration["code"] == provenance["implementation_files"])
    original = run / "input.mp3"
    check("canonical_audio_bytes", digest(original) == args.expected_audio_sha == provenance["source_sha256"], sha256=digest(original))
    check("operator_configuration_hash", hashlib.sha256(json.dumps(records["operator.json"], sort_keys=True).encode()).hexdigest() == provenance["operator_configuration_sha256"])
    run_hash = content_hash(configuration)
    check("configuration_and_run_hashes", run_hash == manifest["run_hash"] == search["run_hash"] == provenance["search_run_hash"], run_hash=run_hash)
    tile_count, points, bad_tiles = 0, 0, []
    for path in sorted((run / "search").glob("tile-*.json")):
        tile = read(path)
        tile_count += 1
        points += tile["payload"]["grid_points"]
        if tile["run_hash"] != run_hash or tile["payload_hash"] != content_hash(tile["payload"]):
            bad_tiles.append(path.name)
    check("checkpoint_payload_hashes", not bad_tiles, checked=tile_count, mismatches=bad_tiles)
    check("checkpoint_work_counts", tile_count == search["tiles_completed"] and points == search["grid_points_searched"], checkpoint_tiles=tile_count, checkpoint_points=points)
    check("decision_result_consistency", result["status"] == decision["status"] and result.get("reason_code") == decision.get("reason_code") and result["candidates"] == decision["candidates"])
    rows, candidates = refinement["ranked"], result["candidates"]
    check("candidate_count_consistency", len(rows) == len(candidates), raw=len(rows), public=len(candidates))
    differences = [i for i, (raw, public) in enumerate(zip(rows, candidates)) if any(not close(raw[k], public[k]) for k in ("lat", "lon", "score"))]
    check("candidate_coordinates_and_scores", not differences, mismatches=differences)
    check("candidate_order", all(a["score"] + 1e-8 >= b["score"] for a, b in zip(rows, rows[1:])))
    prepared = configuration["events"]
    groups = {e.get("harmonic_group_id") or e["event_id"] for e in result["events"]}
    check("every_discovered_group_prepared", len(groups) == len(prepared), discovered=len(groups), prepared=len(prepared))
    start_window = result["recording"]["time_window"]
    low, high = (timestamp(start_window[k]) for k in ("start_utc", "end_utc"))
    outside = [i for i, r in enumerate(rows) if not low - 1e-6 <= r["recording_start_time_s"] <= high + 1e-6]
    check("all_hypothesis_clocks_in_trusted_window", not outside, outside=outside, window_s=[low, high])
    check("shared_clock_evidence", search.get("scoring_time_is_locked") is True and refinement["matching_diagnostics"].get("clock_locked") is True)
    contribution = []
    if rows:
        best, public = rows[0], candidates[0]
        indices = best.get("event_indices", list(range(len(prepared))))
        selected = [prepared[i] for i in indices]
        expected_ids, expected_flights = [], []
        for event, flight in zip(selected, best["flight_ids"]):
            ids = event.get("event_ids", [event["event_id"]])
            expected_ids.extend(ids)
            expected_flights.extend([flight] * len(ids))
        check("matched_groups_and_diagnostic_lengths", len(indices) >= args.expected_groups and len(indices) == len(best["flight_ids"]) == len(best["event_scores"]) == len(best["event_diagnostics"]), matched_groups=len(indices), expected_minimum=args.expected_groups)
        check("original_event_and_flight_mapping", public["event_ids"] == expected_ids and public["flight_ids"] == expected_flights)
        check("public_clock_matches_joint_clock", abs(timestamp(public["recording_start_utc"]) - best["recording_start_time_s"]) <= 1e-6)
        expected_score = sum(best["event_scores"])
        for index, event, value, fit in zip(indices, selected, best["event_scores"], best["event_diagnostics"]):
            quality = event.get("quality", {})
            scale = quality.get("frequency_loss_scale_hz", quality.get("frequency_sigma_hz", max(1.0, quality.get("frequency_uncertainty_hz", 1.0))))
            contribution.append(dict(prepared_index=index, original_event_ids=event.get("event_ids", [event["event_id"]]), residual_score=value, normalized_support=1 + value / (3 * scale), rmse_hz=fit.get("rmse_hz"), sample_count=fit.get("sample_count")))
        check("per_event_residual_evidence", all(close(score, fit["score"]) for score, fit in zip(best["event_scores"], best["event_diagnostics"])))
        if best["score_kind"] == "matched_group_support_minus_normalized_residual":
            check("raw_residual_score_preserved", close(best.get("residual_score", math.inf), expected_score), expected=expected_score, recorded=best.get("residual_score"))
            expected_score = sum(row["normalized_support"] for row in contribution)
        check("all_matched_events_contribute_to_score", close(best["score"], expected_score), expected=expected_score, recorded=best["score"])
        check("diagnostics_match_selected_sensitivity", refinement["matching_diagnostics"].get("sensitivity", {}) == best.get("sensitivity", {}))
    summary = {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": str(run), "source_commit": args.source_commit,
        "auditor_sha256": digest(Path(__file__)),
        "status": result["status"], "reason_code": result.get("reason_code"),
        "integrity_checks_passed": all(c["passed"] for c in checks),
        "accepted_location": result["status"] == "succeeded",
        "localization_accuracy_evaluated": False, "truth_opened": False,
        "scope": "Independent persisted-evidence audit; no producer execution, accuracy acceptance or calibrated uncertainty claim.",
        "files": [{"path": name, "sha256": digest(run / name), "bytes": (run / name).stat().st_size} for name in names],
        "event_contributions": contribution, "checks": checks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: summary[k] for k in ("status", "reason_code", "integrity_checks_passed", "accepted_location", "localization_accuracy_evaluated")}))
    print("Failed checks:", [c["check"] for c in checks if not c["passed"]])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--expected-audio-sha", required=True)
    parser.add_argument("--expected-groups", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    audit(parser.parse_args())
