"""Inspect exact pointwise subset extensions, without changing any decision."""
import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import sys


def canonical(value):
    if isinstance(value, float):
        return {"float64_hex": value.hex()}
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, allow_nan=False).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    verified = json.loads((root / "archive-audit.json").read_bytes())
    manifest = {item["path"]: item for item in verified["release"]["files"]}
    input_hashes = {}

    def read(name):
        raw = (root / "restored/verification" / name).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        assert sha == manifest["verification/" + name]["sha256"]
        input_hashes[name] = sha
        return json.loads(raw)

    source = root / "frozen-runtime/aircraft_geoloc/matching.py"
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    expected = next(item for item in verified["wheel"]["files"] if item["path"] == "src/aircraft_geoloc/matching.py")
    assert source_sha == expected["sha256"]
    sys.path.insert(0, str(root / "frozen-runtime"))
    from aircraft_geoloc.matching import prepare_events, association_score

    search = read("terminal-search-search-report.json")
    refined = read("terminal-refined-candidates.json")
    discovery = read("terminal-discovery-discovery.json")
    events, _ = prepare_events(discovery["events"])

    def event_map(row):
        indices = row["event_indices"]
        fields = ("flight_ids", "pass_emission_times_s", "event_scores", "f0_hz", "event_diagnostics")
        assert len(set(indices)) == len(indices) and all(len(row[field]) == len(indices) for field in fields)
        return {event: {field: row[field][i] for field in fields} for i, event in enumerate(indices)}

    def receiver(row):
        return {key: row[key] for key in ("x", "y", "lat", "lon", "elev_m", "recording_start_time_s", "score_kind")}

    def contributions(row):
        return {index: association_score({"score": score, "event_scores": [score]}, [events[index]])["score"]
                for index, score in zip(row["event_indices"], row["event_scores"])}

    def check(subset, extension):
        a, b = event_map(subset), event_map(extension)
        if not set(a) < set(b):
            return False, "not_strict_event_superset"
        if fingerprint(receiver(subset)) != fingerprint(receiver(extension)):
            return False, "receiver_or_clock_differs"
        if fingerprint(a) != fingerprint({index: b[index] for index in a}):
            return False, "common_assignment_or_fitted_state_differs"
        for state in b.values():
            if state["event_diagnostics"].get("support_fraction") != 1.0:
                return False, "event_fit_not_fully_supported"
        sub_scores, full_scores = contributions(subset), contributions(extension)
        if not all(math.isfinite(value) and value >= 0 for value in full_scores.values()):
            return False, "unsupported_or_negative_added_contribution"
        if not math.isclose(sum(sub_scores.values()), subset["score"], rel_tol=1e-12, abs_tol=1e-12):
            return False, "subset_score_not_additive"
        if not math.isclose(sum(full_scores.values()), extension["score"], rel_tol=1e-12, abs_tol=1e-12):
            return False, "extension_score_not_additive"
        if extension["score"] < subset["score"]:
            return False, "extension_has_lower_recorded_score"
        return True, "exact_pointwise_extension"

    stages, examples = {}, []
    for name, rows in [("coarse", search["coarse_ranked"]), ("fine", search["ranked"]), ("refined", refined["ranked"])]:
        reasons = Counter()
        extensions = []
        with_extension = set()
        for i, subset in enumerate(rows):
            eligible = []
            for j, full in enumerate(rows):
                if not set(subset["event_indices"]) < set(full["event_indices"]):
                    continue
                valid, reason = check(subset, full)
                reasons[reason] += 1
                if valid:
                    eligible.append(j)
            if eligible:
                j = max(eligible, key=lambda k: (len(rows[k]["event_indices"]), rows[k]["score"], -k))
                full = rows[j]
                added = sorted(set(full["event_indices"]) - set(subset["event_indices"]))
                values = contributions(full)
                extensions.append({"subset_index": i, "extension_index": j,
                                   "subset_event_indices": subset["event_indices"], "extension_event_indices": full["event_indices"],
                                   "subset_score": subset["score"], "extension_score": full["score"],
                                   "added_contribution_sum": sum(values[index] for index in added),
                                   "receiver_state_sha256": fingerprint(receiver(subset)),
                                   "common_event_state_sha256": fingerprint(event_map(subset))})
                with_extension.add(i)
                if not examples:
                    examples.append((copy.deepcopy(subset), copy.deepcopy(full)))
        stages[name] = {"records": len(rows), "records_with_exact_pointwise_extension": len(with_extension),
                        "records_without_extension_in_retained_set": len(rows) - len(with_extension),
                        "candidate_pair_classifications": dict(reasons), "extensions": extensions}

    controls = []
    if examples:
        subset, full = examples[0]
        valid, reason = check(subset, full)
        assert valid
        controls.append({"case": "native_exact_extension", "compatible": valid, "reason": reason})
        common = subset["event_indices"][0]
        full_index = full["event_indices"].index(common)
        for name, mutate in [
            ("different_longitude", lambda row: row.__setitem__("lon", row["lon"] + 1e-8)),
            ("different_elevation", lambda row: row.__setitem__("elev_m", row["elev_m"] + .01)),
            ("different_clock", lambda row: row.__setitem__("recording_start_time_s", row["recording_start_time_s"] + 1e-6)),
            ("conflicting_flight", lambda row: row["flight_ids"].__setitem__(full_index, "different-flight")),
            ("different_pass", lambda row: row["pass_emission_times_s"].__setitem__(full_index, row["pass_emission_times_s"][full_index] + 1e-6)),
            ("different_source_fit", lambda row: row["event_diagnostics"][full_index].__setitem__("source_drift_hz", row["event_diagnostics"][full_index]["source_drift_hz"] + 1e-9)),
            ("different_common_loss", lambda row: row["event_scores"].__setitem__(full_index, row["event_scores"][full_index] + 1e-9)),
            ("inconsistent_recorded_score", lambda row: row.__setitem__("score", row["score"] + .1)),
            ("partial_event_support", lambda row: row["event_diagnostics"][-1].__setitem__("support_fraction", .99)),
        ]:
            changed = copy.deepcopy(full)
            mutate(changed)
            valid, reason = check(subset, changed)
            assert not valid, name
            controls.append({"case": name, "compatible": valid, "reason": reason})
    result = {"scope": "Read-only pointwise feasibility diagnostic over retained historical states; not a mode/envelope dominance certificate or new acceptance policy.",
              "runtime_commit": verified["runtime_commit"], "matching_source_sha256": source_sha,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "input_sha256": input_hashes, "stages": stages, "predicate_controls": controls,
              "limitations": ["No truth labels used; no historical decision executed or changed.",
                              "Only observed retained rows were inspected. Discarded or unvisited modes have no inferred classification or bound.",
                              "Receiver/clock and common fitted states are compared exactly using float64 hex values; no distance or parameter tolerance merges states.",
                              "The additive score consistency check uses a 1e-12 numeric tolerance, without changing recorded scores or comparing parameter states approximately.",
                              "A future producer protocol still needs model/domain provenance, completed assessments, retained/discarded ID accounting and counterexample review."]}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"stages": {name: {key: value for key, value in stage.items() if key != "extensions"} for name, stage in stages.items()},
                      "predicate_controls": len(controls)}))


if __name__ == "__main__":
    main()
