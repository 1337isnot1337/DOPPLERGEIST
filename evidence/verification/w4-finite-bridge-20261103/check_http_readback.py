"""Read a computed decision through the real HTTP API; no acoustic search."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import threading
from urllib.request import urlopen

from aircraft_geoloc import confidence
from aircraft_geoloc.contracts import validate_result
from aircraft_geoloc.jobs import JobManager
from aircraft_geoloc.service import JobServer


repo = Path(__file__).resolve().parents[3]
output = Path(sys.argv[1]).resolve()
output.mkdir(parents=True, exist_ok=False)
events, candidates, coverage, diagnostics = runpy.run_path(str(repo / "tests/test_confidence.py"))["near_finite_points"]()
inputs = dict(events=events, candidates=candidates, coverage=coverage, matching_diagnostics=diagnostics)
decision = confidence.decide_location(**inputs)
assert decision["status"] == "succeeded"
job_id = "abb7afeffda8451ba9cb1bd6f8d95707"
directory = output / "jobs" / job_id
directory.mkdir(parents=True)
wire = validate_result(dict(schema_version=1, job_id=job_id, status=decision["status"],
                            stage="complete", progress=1., events=events, coverage=coverage,
                            candidates=decision["candidates"], artifacts={"decision": "decision.json"}))
for name, value in [("result.json", wire), ("decision.json", decision)]:
    (directory / name).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")
(output / "inputs.json").write_text(json.dumps(inputs, indent=2, allow_nan=False)+"\n")
manager = JobManager(output / "jobs")
server = JobServer(("127.0.0.1", 0), manager)
thread = threading.Thread(target=server.serve_forever)
thread.start()
try:
    url = f"http://127.0.0.1:{server.server_port}/api/jobs/{job_id}"
    with urlopen(url) as response:
        result_readback = json.load(response)
    with urlopen(url+"/artifacts/decision.json") as response:
        artifact_readback = json.load(response)
    assert result_readback == wire
    assert artifact_readback == decision
    assert result_readback["candidates"][0]["uncertainty"]["radius_m"] > 159.99
finally:
    server.shutdown()
    server.server_close()
    thread.join()
    manager.close()
modules = repo / "src/aircraft_geoloc"
receipt = {"scope": "Synthetic computed-decision HTTP transport control, no audio/search/accuracy claim",
           "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
           "implementation_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(modules.glob("*.py"))},
           "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "original_radius_m": candidates[0]["uncertainty"]["radius_m"],
           "returned_uncertainty": result_readback["candidates"][0]["uncertainty"],
           "api_matches_saved_wire": result_readback == wire,
           "api_artifact_matches_computed_decision": artifact_readback == decision,
           "browser_rendering_verified": False,
           "limitations": ["Rendering needs a separate browser check.",
                           "Profiles are synthetic decision inputs, not measured physical sensitivity."]}
(output / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False)+"\n")
print(json.dumps({key: value for key, value in receipt.items() if key != "implementation_sha256"}, indent=2))
