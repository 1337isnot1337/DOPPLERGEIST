"""Re-evaluate all frozen readable results without mutating historical evidence."""
import argparse
import json
from pathlib import Path

from dopplergeist.evaluation import evaluate, sha256


def frozen_predictions(root):
    root = Path(root)
    predictions = {}
    for folder in sorted((root / "evidence/results").iterdir()):
        if folder.name == "real-feature-benchmark":
            for row in json.loads((folder / "cases.json").read_text()):
                predictions[f"feature-{row['case']}"] = {
                    "status": "failed" if "error" in row else "inconclusive",
                    "reason_code": "feature_only", "detected": row.get("detected", False),
                    "runtime_s": row.get("elapsed_s"), "peak_memory_bytes": None}
            continue
        report = folder / "report.json"
        if not report.exists():
            predictions[folder.name] = {"status": "failed", "reason_code": "historical_run_no_report"}
            continue
        value = json.loads(report.read_text())
        best = value.get("best")
        predictions[folder.name] = {"status": "succeeded" if best else "failed",
            "candidates": [best] if best else [], "runtime_s": value.get("elapsed_s"), "peak_memory_bytes": None}
    return predictions


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    base = args.root / "benchmarks"
    manifest = json.loads((base / "frozen-manifest.json").read_text())
    truth = json.loads((base / "truth/frozen-labels.json").read_text())
    predictions = frozen_predictions(args.root)
    # Preserve the historical acceptance threshold while also reporting tiers.
    result = evaluate(manifest, predictions, truth, threshold_m=100)
    result["evidence_sha256"] = {str(p.relative_to(args.root)): sha256(p)
        for p in sorted((args.root / "evidence/results").rglob("*.json"))}
    result["limits"].append("Frozen feature recall is annotation-band-assisted case detection, not automatic event-window recall.")
    result["limits"].append("Peak memory was not recorded historically and is left null.")
    for name, value in (("predictions.json", predictions), ("report.json", result)):
        (args.output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result["summary"], indent=2))
