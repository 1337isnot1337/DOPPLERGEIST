"""Propose bootstrap witnesses from an existing, truth-separated search."""
import argparse
import json
import math
from pathlib import Path

from dopplergeist.data_access import content_hash
from dopplergeist.finite_search import RetentionLedger, classified_assessment, identify_mode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("search", type=Path, help="previous search directory with completed tile receipts")
    parser.add_argument("--out", type=Path, required=True, help="new bootstrap.json path")
    args = parser.parse_args()
    manifest = json.loads((args.search / "manifest.json").read_text())
    if content_hash(manifest["configuration"]) != manifest["run_hash"]:
        raise ValueError("Previous search manifest is corrupt")
    top_k = manifest["configuration"]["budget"]["top_k"]
    kind = "matched_group_support_minus_normalized_residual"
    if not (args.search / "retention.sqlite").is_file():
        raise ValueError("Previous search has no retention ledger")
    ledger = RetentionLedger(args.search / "retention.sqlite", manifest["run_hash"], kind)
    candidates = {}
    for path in sorted(args.search.glob("tile-*.json")):
        if path.name.endswith(".error.json"):
            continue
        record = json.loads(path.read_text())
        payload = record["payload"]
        if record.get("run_hash") != manifest["run_hash"] or record.get("payload_hash") != content_hash(payload):
            raise ValueError(f"Corrupt prior checkpoint: {path.name}")
        rows = [row for row in payload.get("ranked", [])
                if row.get("core_assessment_complete") is True and row.get("score_kind") == kind
                and math.isfinite(row["score"]) and classified_assessment(row)]
        if not rows:
            continue
        stage = "coarse:" + path.stem[len("tile-"):]
        if not ledger.stage_valid(stage, payload.get("retention_checksum")):
            raise ValueError(f"Invalid prior retention ledger: {stage}")
        for row in rows:
            identify_mode(row)  # Verify the saved mode identity before using it.
            seed = row["mode_seed"]
            witness = {"position_m": seed["position"][:2], "event_indices": seed["event_indices"],
                       "flight_ids": seed["flight_ids"], "pass_emission_times_s": seed["pass_emission_times_s"]}
            key = content_hash(witness)
            if key not in candidates or row["score"] > candidates[key][0]:
                candidates[key] = (row["score"], witness)
    if len(candidates) < top_k:
        raise ValueError(f"Need {top_k} distinct fully assessed modes; found {len(candidates)}")
    selected = sorted(candidates.items(), key=lambda item: (-item[1][0], item[0]))[:top_k]
    document = {"schema_version": 1, "source_run_hash": manifest["run_hash"],
                "witnesses": [item[1][1] for item in selected]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as target:
        target.write(json.dumps(document, indent=2, allow_nan=False) + "\n")
    print(f"Proposed {len(selected)} witnesses; the new search must validate them before using any floor.")


if __name__ == "__main__":
    main()
