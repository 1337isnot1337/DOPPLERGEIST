"""Verifier regressions using archived real-recording observations only."""
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("verify_real_upload_evidence",
    ROOT / "scripts/verify_upload_http.py")
HTTP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HTTP)


def observed_harmonic_identities():
    source = ROOT / "evidence/audio/w1-fragments-20261102/reference-discovery/discovery.json"
    discovery = json.loads(source.read_text())
    # The historical producer saved one event per group and all measured ridges
    # separately. Express those same observed groups as the current producer's
    # one-record-per-ridge identities; no audio or trajectory is generated.
    identities = []
    for event, ridges in zip(discovery["events"], discovery["harmonic_ridges"], strict=True):
        for index, _ in enumerate(ridges):
            identities.append({"event_id": f"{event['event_id']}-ridge-{index + 1}",
                               "harmonic_group_id": event["harmonic_group_id"]})
    assert len(discovery["events"]) == 6 and len(identities) == 7
    return identities


def test_real_harmonic_records_keep_independent_event_and_ridge_counts():
    events = observed_harmonic_identities()
    assert HTTP.inspect_discovery_counts(events, {"discovered_events": 6, "discovered_ridges": 7}) == {
        "event_groups": 6, "ridge_records": 7}
    with pytest.raises(ValueError, match="independent-event count"):
        HTTP.inspect_discovery_counts(events, {"discovered_events": 7, "discovered_ridges": 7})
    with pytest.raises(ValueError, match="discovered-ridge count"):
        HTTP.inspect_discovery_counts(events, {"discovered_events": 6, "discovered_ridges": 6})


def test_historical_real_group_count_remains_verifiable():
    source = ROOT / "evidence/audio/w1-fragments-20261102/reference-discovery/discovery.json"
    events = json.loads(source.read_text())["events"]
    assert HTTP.inspect_discovery_counts(events, {"discovered_events": 6}) == {
        "event_groups": 6, "ridge_records": 6}


def test_completed_real_upload_needing_time_does_not_satisfy_full_pipeline():
    root = ROOT / "evidence/e2e-worker-20261103"
    receipt = json.loads((root / "real-http-verification.json").read_text())
    evidence = json.loads((root / "real-pipeline-evidence.json").read_text())
    assert receipt["verification_passed"] is True
    assert receipt["status"] == "needs_input"
    assert evidence["passed"] is True
    assert HTTP.complete_pipeline_with_candidates(evidence, receipt["candidate_count"]) is False
