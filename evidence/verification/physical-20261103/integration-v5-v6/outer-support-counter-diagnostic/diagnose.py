"""Exercise the exact pure coverage adapter against the added producer counter."""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "rev-parse", args.ref], cwd=args.repo).decode().strip()
    raw = subprocess.check_output(["git", "show", f"{commit}:src/aircraft_geoloc/automatic.py"], cwd=args.repo)
    parsed = ast.parse(raw)
    function = next(node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == "_coverage")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), f"{commit}:automatic.py:_coverage", "exec"), namespace)
    coverage = namespace["_coverage"]
    request = json.loads(args.request.read_bytes())
    baseline = {"tiles_total": 1, "tiles_completed": 1, "tile_failures": [], "refinement_failure": None,
                "all_event_groups_considered": True, "data_scope_complete": True,
                "model_support_complete": True,
                "model_support": {"unsupported_cpa_track_evaluations": 0, "unclassified_score_candidates": 0,
                                  "evaluated_trials": 1, "rejected_trials": 0, "unknown_trials": 0,
                                  "unreported_trial_envelopes": 0, "diagnostics_directory": "support"}}
    cases = []
    for name, value in [("zero", 0), ("nonzero", 1), ("negative", -1),
                        ("boolean", True), ("string", "1"), ("absent", None)]:
        search = copy.deepcopy(baseline)
        if value is None:
            search["model_support"].pop("unreported_trial_envelopes")
        else:
            search["model_support"]["unreported_trial_envelopes"] = value
        before = copy.deepcopy(search)
        result = coverage(request, search, {})
        assert search == before
        cases.append({"case": name, "unreported_trial_envelopes": value,
                      "search_complete": result["search_complete"], "data_status": result["data_status"],
                      "limitations": result["limitations"]})
    native_consistent = copy.deepcopy(baseline)
    native_consistent["model_support_complete"] = False
    native_consistent["model_support"]["unclassified_score_candidates"] = 1
    native_consistent["model_support"]["unreported_trial_envelopes"] = 1
    consistent = coverage(request, native_consistent, {})
    assert consistent["search_complete"] is False
    output = {"scope": "Exact standalone _coverage function contract diagnostic; no pipeline job or scientific acceptance test.",
              "commit": commit, "source_sha256": hashlib.sha256(raw).hexdigest(),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "request_sha256": hashlib.sha256(args.request.read_bytes()).hexdigest(),
              "cases": cases, "consistent_producer_unknown_envelope": consistent,
              "interpretation": "W2 reports unreported envelopes with model_support_complete=false and an unclassified candidate, which already abstains. The added counter itself still needs an explicit product transport/validation contract."}
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"commit": commit, "cases": [{"case": c["case"], "search_complete": c["search_complete"]} for c in cases],
                      "consistent_producer_case_search_complete": consistent["search_complete"]}))


if __name__ == "__main__":
    main()
