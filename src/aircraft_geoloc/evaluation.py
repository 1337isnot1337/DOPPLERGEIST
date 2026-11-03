"""Post-run evaluation only. Never import this module from a search worker.

The manifest is label free; the caller supplies truth after predictions exist.
All cases, including absent predictions and execution failures, stay in reports.
"""
import hashlib
import math


def sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def distance_m(a, b):
    """WGS84 ellipsoidal surface distance, with coordinates in lat/lon order."""
    from pyproj import Geod
    return abs(Geod(ellps="WGS84").inv(a[1], a[0], b[1], b[0])[2])


def _groups(events):
    groups = {}
    for index, event in enumerate(events):
        start, end = event["start_s"], event["end_s"]
        if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
            raise ValueError("Event intervals must be finite, nonnegative and increasing")
        key = event.get("harmonic_group_id", f"ungrouped-{index}")
        if key not in groups:
            groups[key] = [start, end]
        else:
            groups[key] = [min(start, groups[key][0]), max(end, groups[key][1])]
    return list(groups.values())


def detection_counts(expected, observed, iou_threshold=0.3):
    """Maximum cardinality interval matching; harmonics count once per flyover."""
    if not 0 < iou_threshold <= 1:
        raise ValueError("IoU threshold must lie in (0, 1]")
    truth, predictions = _groups(expected), _groups(observed)
    edges = []
    for start, end in predictions:
        edges.append([j for j, (a, b) in enumerate(truth)
                      if max(0, min(end, b) - max(start, a)) /
                      (max(end, b) - min(start, a)) >= iou_threshold])
    matched = {}

    def augment(i, seen):
        for j in edges[i]:
            if j not in seen:
                seen.add(j)
                if j not in matched or augment(matched[j], seen):
                    matched[j] = i
                    return True
        return False

    hits = sum(augment(i, set()) for i in range(len(predictions)))
    return {"true_positives": hits, "misses": len(truth) - hits,
            "false_alarms": len(predictions) - hits}


def evaluate(manifest, predictions, truth, threshold_m=100, iou_threshold=0.3):
    """Join case-ID keyed result/truth dictionaries, preserving the manifest order.

    Eligible real cases require independently established clock and location.
    Ineligible references may still have a descriptive distance, excluded from
    accuracy aggregates. A raw coordinate without status=succeeded is no fix.
    """
    if not math.isfinite(threshold_m) or threshold_m <= 0:
        raise ValueError("Distance threshold must be positive and finite")
    rows = []
    ids = [c["case_id"] for c in manifest["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case IDs")
    if set(predictions) - set(ids) or set(truth) - set(ids):
        raise ValueError("Predictions/truth contain cases absent from manifest")
    for case in manifest["cases"]:
        key = case["case_id"]
        label = truth.get(key, {})
        result = predictions.get(key, {})
        status = result.get("status", "missing")
        if status not in {"succeeded", "inconclusive", "failed", "needs_input", "cancelled", "missing"}:
            raise ValueError(f"Nonterminal or unknown status for {key}: {status}")
        if label.get("location_accuracy_eligible") and "location" not in label:
            raise ValueError(f"Eligible case {key} lacks a location reference")
        row = {"case_id": key, "split": case["split"], "scope": case["scope"],
               "status": status, "reason_code": result.get("reason_code"),
               "location_accuracy_eligible": label.get("location_accuracy_eligible", False),
               "eligibility_limit": label.get("eligibility_limit"),
               "runtime_s": result.get("runtime_s"), "peak_memory_bytes": result.get("peak_memory_bytes")}
        if "events" in label:
            counts = detection_counts(label["events"], result.get("events", []), iou_threshold)
            row.update(counts)
        if "detected" in label:
            observed = result.get("detected", False)
            row.update(true_positives=int(label["detected"] and observed),
                       misses=int(label["detected"] and not observed),
                       false_alarms=int(not label["detected"] and observed))
        candidates = result.get("candidates", [])
        located = status == "succeeded"
        if located and not candidates:
            raise ValueError(f"Successful result for {key} has no candidate")
        row["location_returned"] = located
        if located:
            best = candidates[0]
            for name, low, high in (("lat", -90, 90), ("lon", -180, 180)):
                if not math.isfinite(best[name]) or not low <= best[name] <= high:
                    raise ValueError(f"Invalid {name} for {key}")
            if "location" in label:
                row["location_error_m"] = distance_m([best["lat"], best["lon"]], label["location"])
                row["within_threshold"] = row["location_error_m"] <= threshold_m
            if "flight_ids" in label:
                row["flight_ids_correct"] = best.get("flight_ids") == label["flight_ids"]
            # A wrong association is a false localization even if spatially close.
            row["false_localization"] = bool(
                label.get("expect_inconclusive", False) or
                row.get("flight_ids_correct") is False or
                (row["location_accuracy_eligible"] and not row.get("within_threshold", False)))
        rows.append(row)

    def summarize(selected):
        n = len(selected)
        eligible = [r for r in selected if r["location_accuracy_eligible"]]
        fixes = [r for r in eligible if r["location_returned"]]
        tp = sum(r.get("true_positives", 0) for r in selected)
        fn = sum(r.get("misses", 0) for r in selected)
        fp = sum(r.get("false_alarms", 0) for r in selected)
        assessed = [r for r in selected if r["location_accuracy_eligible"] or
                    truth.get(r["case_id"], {}).get("expect_inconclusive", False)]
        false = sum(r.get("false_localization", False) for r in assessed)
        return {"cases": n, "eligible_location_cases": len(eligible),
                "successful_locations_within_threshold": sum(r.get("within_threshold", False) and
                    not r.get("false_localization", False) for r in fixes),
                "localization_errors_m": [r["location_error_m"] for r in fixes if "location_error_m" in r],
                "false_localizations": false,
                "false_localization_rate": false / len(assessed) if assessed else None,
                "false_localization_denominator": len(assessed),
                "inconclusive_rate": sum(r["status"] == "inconclusive" for r in selected) / n if n else None,
                "execution_failures": sum(r["status"] in {"failed", "missing"} for r in selected),
                "needs_input": sum(r["status"] == "needs_input" for r in selected),
                "detection_true_positives": tp, "detection_misses": fn, "detection_false_alarms": fp,
                "detection_recall": tp / (tp + fn) if tp + fn else None,
                "detection_precision": tp / (tp + fp) if tp + fp else None}

    return {"schema_version": 1, "threshold_m": threshold_m, "event_iou_threshold": iou_threshold,
            "cases": rows, "summary": summarize(rows),
            "by_split": {split: summarize([r for r in rows if r["split"] == split])
                         for split in sorted({r["split"] for r in rows})},
            "by_scope": {scope: summarize([r for r in rows if r["scope"] == scope])
                         for scope in sorted({r["scope"] for r in rows})},
            "limits": ["Synthetic and manually configured regional results do not validate automatic national search.",
                       "Uncalibrated sensitivity is not a coverage probability."]}
