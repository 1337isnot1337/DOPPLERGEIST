#!/usr/bin/env python3
"""Compare two completed real verify_upload_http.py runs without rerunning fits.

Exit zero requires verified full workflows and exact scientific parity. JSON
numbers have no tolerance. Search checkpoints and logical retention rows are
included. The existing verifier owns input and artifact integrity checks.
An explicit continuation report can qualify a resumed baseline for scientific
comparison, but its cumulative active cost is never labeled a fresh-run speedup.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime
import hashlib
from itertools import zip_longest
import json
import math
from pathlib import Path
import sqlite3


IMPLEMENTATION_FIELDS = {"implementation_files", "run_hash", "search_run_hash",
                         "source_fit_code_sha256", "score_code_sha256", "verifier_sha256"}
PERFORMANCE_FIELDS = {"elapsed_s", "process_peak_rss_mib"}
ROOT_JSON = ("upload-request.json", "operator.json", "result.json")
REQUIRED_STAGES = {"automatic_provenance", "intake", "discovery", "acquisition",
                   "search", "refinement", "decision"}
MISSING = object()


def read_json(path):
    def reject(value):
        raise ValueError(f"Nonfinite JSON constant in {path}: {value}")
    return json.loads(path.read_text(), parse_constant=reject)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def summary_value(value):
    if value is MISSING:
        return {"missing": True}
    if isinstance(value, (dict, list)) or (isinstance(value, str) and len(value) > 500):
        return {"type": type(value).__name__, "length": len(value),
                "sha256": hashlib.sha256(encoded(value)).hexdigest()}
    return value


class Differences:
    def __init__(self, limit):
        self.limit, self.count = limit, 0
        self.examples, self.categories, self.files = [], Counter(), set()
        self.numeric_count, self.maximum_absolute_numeric_difference = 0, 0.0

    def add(self, artifact, path, left, right):
        self.count += 1
        self.files.add(artifact)
        category = "job/search/tile-*.json" if artifact.startswith("job/search/tile-") else artifact
        self.categories[category] += 1
        detail = {"artifact": artifact, "path": "/" + "/".join(map(str, path)),
                  "baseline": summary_value(left), "current": summary_value(right)}
        if type(left) in (int, float) and type(right) in (int, float):
            absolute = abs(right - left)
            self.numeric_count += 1
            self.maximum_absolute_numeric_difference = max(self.maximum_absolute_numeric_difference, absolute)
            detail["absolute_difference"] = absolute
        if len(self.examples) < self.limit:
            self.examples.append(detail)

    def compare(self, artifact, left, right, path=()):
        if type(left) is not type(right):
            self.add(artifact, path, left, right)
        elif isinstance(left, dict):
            for key in sorted(left.keys() | right.keys()):
                if key not in left or key not in right:
                    self.add(artifact, path + (key,), left.get(key, MISSING), right.get(key, MISSING))
                else:
                    self.compare(artifact, left[key], right[key], path + (key,))
        elif isinstance(left, list):
            if len(left) != len(right):
                self.add(artifact, path + ("length",), len(left), len(right))
            for index, (a, b) in enumerate(zip_longest(left, right, fillvalue=MISSING)):
                if a is MISSING or b is MISSING:
                    self.add(artifact, path + (index,), a, b)
                else:
                    self.compare(artifact, a, b, path + (index,))
        elif left != right or (isinstance(left, float) and left == 0
                               and math.copysign(1, left) != math.copysign(1, right)):
            self.add(artifact, path, left, right)

    def report(self):
        return {"count": self.count, "changed_artifact_count": len(self.files),
                "counts_by_artifact": dict(sorted(self.categories.items())),
                "numeric_difference_count": self.numeric_count,
                "maximum_absolute_numeric_difference": self.maximum_absolute_numeric_difference,
                "examples": self.examples, "examples_truncated": self.count > len(self.examples)}


class Run:
    def __init__(self, directory, continuation=None):
        self.directory = directory.resolve()
        if (self.directory / "continuation-start.json").exists() and continuation is None:
            raise ValueError("This job has a continuation; supply its completed --baseline-continuation report")
        # This receipt is committed after service shutdown and verifier checks.
        # Refuse to inspect any job or SQLite database before it exists.
        receipt = self.directory / "http-verification.json"
        if not receipt.is_file():
            raise ValueError(f"Run has no completed HTTP verification receipt: {directory}")
        self.receipt = read_json(receipt)
        if "finished_utc" not in self.receipt or "elapsed_s" not in self.receipt:
            raise ValueError(f"HTTP verification receipt is unfinished: {directory}")
        if self.receipt.get("service", {}).get("returncode") is None:
            raise ValueError(f"Service termination is not established; refusing to inspect its ledger: {directory}")
        self.continuation = read_json(continuation) if continuation is not None else None
        if self.continuation is not None:
            record = self.continuation
            if (record.get("scope") != "resumed_automatic_baseline_continuation"
                    or record.get("resumed_baseline") is not True or record.get("fresh_run") is not False
                    or record.get("job_id") != self.receipt["job_id"]
                    or Path(record["baseline_directory"]).resolve() != self.directory):
                raise ValueError("Continuation report does not identify this resumed baseline")
            if record.get("worker_shutdown_confirmed") is not True:
                raise ValueError("Continuation worker shutdown is not confirmed; refusing to inspect its ledger")
        self.job = self.directory / "jobs" / self.receipt["job_id"]
        self.final = read_json(self.job / "result.json")
        if self.final.get("status") in {"running", "queued"}:
            raise ValueError("Job is active; refusing to inspect its ledger")
        self.ignored = Counter()

    def normalize(self, value, relative, root=False, path=()):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                here = path + (key,)
                reason = None
                if key in IMPLEMENTATION_FIELDS:
                    reason = f"field:{key}"
                elif key in PERFORMANCE_FIELDS:
                    reason = f"performance:{key}"
                elif not root and relative == "provenance.json" and here == ("operator_configuration_sha256",):
                    reason = "operator configuration digest; full normalized operator.json is compared"
                elif not root and relative == "search/manifest.json" and here == ("configuration", "code"):
                    reason = "search implementation files"
                elif not root and relative == "search/manifest.json" and here in {
                        ("configuration", "runtime", "ridge_fit_backend"),
                        ("configuration", "runtime", "acoustic_backend")}:
                    reason = "search native implementation metadata:" + key
                elif not root and relative == "provenance.json" and here == ("resumed_from",):
                    reason = "explicit resume metadata: resumed_from"
                elif not root and relative == "search/search-report.json" and here == ("tiles_resumed",):
                    reason = "explicit resume performance metadata: tiles_resumed"
                if reason:
                    self.ignored[reason] += 1
                    continue
                normalized_key = self.normalize(key, relative, root, path)
                result[normalized_key] = self.normalize(item, relative, root, here)
            return result
        if isinstance(value, list):
            return [self.normalize(item, relative, root, path + (index,)) for index, item in enumerate(value)]
        if isinstance(value, str):
            return (value.replace(str(self.job), "<job>")
                    .replace(str(self.directory), "<run>")
                    .replace(self.receipt["job_id"], "<job-id>"))
        return value

    def json(self, relative, *, root=False):
        return self.normalize(read_json((self.directory if root else self.job) / relative), relative, root)

    def full_pipeline(self):
        if self.continuation is not None:
            record = self.continuation
            evidence = record.get("pipeline_evidence", {})
            segments = record.get("segments", [])
            timed = (len(segments) >= 2 and all(
                isinstance(segment.get(key), (int, float)) and not isinstance(segment.get(key), bool)
                and math.isfinite(segment[key]) and segment[key] >= 0
                for segment in segments for key in ("wall_s", "cpu_s")))
            timed = timed and all(math.isclose(record.get(total, -1), sum(segment[key] for segment in segments),
                                               rel_tol=1e-12, abs_tol=1e-9)
                                  for key, total in (("wall_s", "cumulative_active_wall_s"),
                                                     ("cpu_s", "cumulative_cpu_s")))
            return (all(record.get(key) is True for key in
                        ("original_http_receipt_unchanged", "implementation_unchanged",
                         "worker_shutdown_confirmed", "pipeline_evidence_passed",
                         "full_pipeline_observed", "full_pipeline_requirements_met"))
                    and timed and segments[-1].get("returncode") == 0
                    and record.get("final_status") == self.final.get("status")
                    and record.get("reason_code") == self.final.get("reason_code")
                    and record.get("candidate_count") == len(self.final.get("candidates", [])) > 0
                    and record.get("event_count") == len(self.final.get("events", []))
                    and record.get("source_sha256") == self.receipt.get("source_sha256")
                    and self.final.get("recording", {}).get("source_sha256") == self.receipt.get("source_sha256")
                    and evidence.get("passed") is True and evidence.get("full_pipeline_observed") is True
                    and REQUIRED_STAGES.issubset(evidence.get("stages_verified", [])))
        evidence = read_json(self.directory / "pipeline-evidence.json")
        return (all(self.receipt.get(key) is True for key in
                    ("verification_passed", "http_checks_passed", "pipeline_evidence_passed",
                     "full_pipeline_observed", "full_pipeline_requirements_met"))
                and self.receipt.get("candidate_count", 0) > 0
                and evidence.get("passed") is True and evidence.get("full_pipeline_observed") is True
                and REQUIRED_STAGES.issubset(evidence.get("stages_verified", [])))

    def timing(self):
        rows = [json.loads(line) for line in (self.directory / "history.jsonl").read_text().splitlines()]
        timestamp = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        transitions = []
        for row in rows:
            result = row["result"]
            stage = result.get("stage") if result["status"] in ("running", "queued") else "terminal:" + result["status"]
            if not transitions or transitions[-1]["stage"] != stage:
                transitions.append({"stage": stage, "observed_utc": row["observed_utc"]})
        totals = Counter()
        for current, following in zip(transitions, transitions[1:]):
            duration = timestamp(following["observed_utc"]) - timestamp(current["observed_utc"])
            current["until_next_transition_s"] = duration
            totals[current["stage"]] += duration
        result = {"receipt_elapsed_s": self.receipt["elapsed_s"], "poll_records": len(rows),
                  "observed_stage_seconds": dict(totals), "transitions": transitions,
                  "note": "Stage durations use first observed HTTP transitions and include polling uncertainty; unobserved short stages have no inferred duration."}
        if self.continuation is not None:
            result["continuation"] = {key: self.continuation[key] for key in
                                      ("segments", "cumulative_active_wall_s", "cumulative_cpu_s")}
            result["note"] += " History describes the original HTTP attempt only. Continuation segments exclude idle time between attempts and are not a fresh run."
        return result


def ignored_artifact(relative):
    return (relative in {"resume.json", "intake/intake.json"}
            or relative.startswith("search/.tile-workers/")
            or (relative.startswith("result-before-resume-") and relative.endswith(".json")))


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def compare_ledger(left, right, relative, differences):
    artifact = "job/" + relative
    with ExitStack() as stack:
        databases = []
        for run in (left, right):
            connection = sqlite3.connect((run.job / relative).as_uri() + "?mode=ro", uri=True)
            stack.callback(connection.close)
            databases.append(connection)
        table_sets = [{row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                      for db in databases]
        differences.compare(artifact, sorted(table_sets[0]), sorted(table_sets[1]), ("tables",))
        counts = [{}, {}]
        for table in sorted(table_sets[0] & table_sets[1]):
            schemas = [db.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall() for db in databases]
            differences.compare(artifact, schemas[0], schemas[1], (table, "schema"))
            cursors, columns = [], []
            for db, schema in zip(databases, schemas):
                names = [row[1] for row in schema]
                columns.append(names)
                keys = [row[1] for row in sorted(schema, key=lambda row: row[5]) if row[5]] or names
                order = ",".join(map(quote_identifier, keys))
                cursors.append(db.execute(f"SELECT * FROM {quote_identifier(table)} ORDER BY {order}"))
            for number, rows in enumerate(zip_longest(*cursors, fillvalue=MISSING)):
                normalized = []
                for side, row in enumerate(rows):
                    if row is MISSING:
                        normalized.append(MISSING)
                        continue
                    record = dict(zip(columns[side], row))
                    if table == "run":
                        record.pop("identity", None)
                    for field in ({"stages": ("kept",), "records": ("seed",), "bounds": ("detail",)}.get(table, ())):
                        record[field] = json.loads(record[field])
                    counts[side][table] = counts[side].get(table, 0) + 1
                    normalized.append(record)
                if any(row is MISSING for row in normalized):
                    differences.add(artifact, (table, number), *normalized)
                else:
                    differences.compare(artifact, *normalized, (table, number))
        return {"baseline_rows": counts[0], "current_rows": counts[1]}


def compare_runs(baseline, current, max_examples=40, baseline_continuation=None):
    left, right = Run(baseline, baseline_continuation), Run(current)
    differences, checked, ledgers = Differences(max_examples), Counter(), {}
    selected = [{path.relative_to(run.job).as_posix() for path in run.job.rglob("*")
                 if path.is_file() and path.suffix in {".json", ".sqlite"}
                 and not ignored_artifact(path.relative_to(run.job).as_posix())} for run in (left, right)]
    differences.compare("job inventory", sorted(selected[0]), sorted(selected[1]))
    for name in sorted(selected[0] & selected[1]):
        try:
            if name.endswith(".json"):
                differences.compare("job/" + name, left.json(name), right.json(name))
                checked["json"] += 1
            elif name.endswith(".sqlite"):
                ledgers[name] = compare_ledger(left, right, name, differences)
                checked["sqlite"] += 1
        except (OSError, ValueError, sqlite3.DatabaseError) as error:
            differences.add("job/" + name, ("comparison_error",), str(error), MISSING)
    for name in ROOT_JSON:
        if name == "result.json" and left.continuation is not None:
            # The root result is the original HTTP snapshot, possibly absent
            # after a timeout. The final job/result.json is compared above.
            continue
        differences.compare("root/" + name, left.json(name, root=True), right.json(name, root=True))
        checked["root_json"] += 1
    differences.compare("HTTP source identity", {key: left.receipt.get(key) for key in ("source_sha256", "source_bytes")},
                        {key: right.receipt.get(key) for key in ("source_sha256", "source_bytes")})
    full = {name: run.full_pipeline() for name, run in (("baseline", left), ("current", right))}
    passed = differences.count == 0 and all(full.values())
    timings = {name: run.timing() for name, run in (("baseline", left), ("current", right))}
    return {"scope": "Exact semantic comparison of actual upload workflows, with explicit continuation evidence when supplied",
            "baseline": str(left.directory), "current": str(right.directory),
            "run_kinds": {"baseline": "resumed_baseline" if left.continuation is not None else "fresh_http",
                          "current": "fresh_http"},
            "passed": passed, "scientific_payloads_exact": differences.count == 0,
            "full_pipeline_verified": full,
            "checked_artifacts": dict(checked), "retention_ledgers": ledgers,
            "outcomes": {name: {"status": run.final.get("status"), "reason_code": run.final.get("reason_code"),
                                "candidate_count": len(run.final.get("candidates", [])),
                                "event_count": len(run.final.get("events", []))}
                         for name, run in (("baseline", left), ("current", right))},
            "original_http_outcomes": {name: {key: run.receipt.get(key) for key in
                                              ("status", "reason_code", "verification_passed", "full_pipeline_observed")}
                                       for name, run in (("baseline", left), ("current", right))},
            "differences": differences.report(), "timings": timings,
            "verified_full_workflow_speedup": (left.receipt["elapsed_s"] / right.receipt["elapsed_s"]
                                               if passed and left.continuation is None else None),
            "resumed_active_wall_to_current_receipt_ratio": (
                left.continuation["cumulative_active_wall_s"] / right.receipt["elapsed_s"]
                if passed and left.continuation is not None else None),
            "normalization": {"implementation_fields": sorted(IMPLEMENTATION_FIELDS),
                "native_backend_metadata": ["search/manifest.json/configuration/runtime/ridge_fit_backend",
                                            "search/manifest.json/configuration/runtime/acoustic_backend"],
                "performance_fields": sorted(PERFORMANCE_FIELDS),
                "path_rule": "Only each run directory, job directory and exact job identifier are replaced.",
                "sqlite_rule": "Compare all logical tables, columns and rows; ignore only run.identity and physical SQLite/index layout.",
                "excluded_metadata": ["resume.json", "intake/intake.json", "search/.tile-workers/**",
                                      "result-before-resume-*.json", "provenance.json/resumed_from",
                                      "search/search-report.json/tiles_resumed"],
                "scope": "Scientific JSON and logical ledger contents. Existing HTTP verification owns integrity checks; real-audio validation separately checks measured arrays.",
                "observed_ignored_counts": {"baseline": dict(left.ignored), "current": dict(right.ignored)}},
            "limitations": ["Exact parity establishes consistency with the baseline, not geolocation accuracy.",
                            "No withheld-location comparison or synthetic observations are used.",
                            "A resumed baseline retains its unsuccessful original HTTP receipt. Its cumulative active cost includes restart/replay overhead and is not uninterrupted runtime.",
                            "All semantic differences fail the gate, including floating-point roundoff; examples alone are bounded."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--baseline-continuation", type=Path,
                        help="Explicit completed continuation evidence; never rewrites the original HTTP receipt")
    parser.add_argument("--output", type=Path, required=True, help="New JSON report path")
    parser.add_argument("--max-examples", type=int, default=40)
    args = parser.parse_args()
    if args.max_examples < 1:
        parser.error("--max-examples must be positive")
    report = compare_runs(args.baseline, args.current, args.max_examples, args.baseline_continuation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"report": str(args.output), "passed": report["passed"],
                      "scientific_payloads_exact": report["scientific_payloads_exact"],
                      "semantic_differences": report["differences"]["count"],
                      "full_pipeline_verified": report["full_pipeline_verified"],
                      "run_kinds": report["run_kinds"],
                      "verified_full_workflow_speedup": report["verified_full_workflow_speedup"],
                      "resumed_active_wall_to_current_receipt_ratio": report["resumed_active_wall_to_current_receipt_ratio"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
