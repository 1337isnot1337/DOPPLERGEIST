"""Exercise frozen engineering decision checks; this is not audio accuracy."""
import argparse
import json
from pathlib import Path

from dopplergeist.confidence import decide_location
from dopplergeist.evaluation import evaluate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = json.loads((args.root / "benchmarks/decision-inputs.json").read_text())
    predictions = {}
    for case in cases["cases"]:
        result = decide_location(case["events"], case["candidates"], case["coverage"],
                                 matching_diagnostics=case["matching_diagnostics"])
        result["candidates"] = case["candidates"]
        result["events"] = case["events"]
        predictions[case["case_id"]] = result
    # Persist predictions before opening the separate truth file.
    (args.output / "predictions.json").write_text(json.dumps(predictions, indent=2, allow_nan=False) + "\n")
    truth = json.loads((args.root / "benchmarks/truth/decision-labels.json").read_text())
    report = evaluate(cases, predictions, truth)
    report["limits"].append("Decision-only simulated evidence fixtures; no acoustic or geographic accuracy validation.")
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report["by_split"], indent=2))
