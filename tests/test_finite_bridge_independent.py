"""Actual ledger -> product -> decision controls; no acoustic accuracy claim."""
from copy import deepcopy
import json
import sqlite3
import threading
from urllib.request import urlopen

import pytest
from pyproj import Geod

from aircraft_geoloc.automatic import _decide
from aircraft_geoloc.contracts import validate_result
from aircraft_geoloc.finite_search import RetentionLedger, classified_assessment
from aircraft_geoloc.jobs import JobManager
from aircraft_geoloc.service import JobServer
from aircraft_geoloc.tiled_search import merge_candidates


@pytest.mark.parametrize("case,reason", [
    ("complete", "supported_by_evidence_checks"),
    ("unassessed", "finite_modes_not_assessed"),
    ("near_discard", "retention_may_hide_alternatives"),
    ("corrupt", "finite_search_incomplete"),
])
def test_actual_retention_evidence_survives_the_product_boundary(tmp_path, case, reason):
    events = [{"event_id": f"e{i}", "harmonic_group_id": f"g{i}",
               "start_s": i*100., "end_s": i*100.+20., "band_hz": [90., 200.],
               "ridge": [{"time_s": i*100.+t, "frequency_hz": 140.-t}
                         for t in (0., 10., 20.)]} for i in range(2)]
    fit = {"score": -.5, "rmse_hz": .5, "outlier_fraction": 0.,
           "support_fraction": 1., "drift_at_bound": False}
    profile = {"complete": True, "boundary_limited": False, "radius_m": 70.,
               "method": "synthetic_complete_profile", "kind": "sensitivity",
               "sources": ["frequency", "clock", "altitude", "sound_speed"]}
    rows = []
    for distance, score in [(0., -1.), (90., -1.2), (2000., -1.3 if case == "near_discard" else -5.)]:
        lon, lat, _ = Geod(ellps="WGS84").fwd(-100., 40., 90., distance)
        row = {"x": distance, "y": 0., "lat": lat, "lon": lon, "elev_m": 10.,
               "recording_start_time_s": 1790000000., "flight_ids": ["a", "b"],
               "event_indices": [0, 1], "pass_emission_times_s": [1790000010., 1790000110.],
               "score": score, "score_kind": "negative_robust_ridge_loss_hz",
               "event_diagnostics": [dict(fit), dict(fit)], "sensitivity": deepcopy(profile),
               "scoring_assessment": {"complete": True, "evaluated_trials": 2,
                                      "rejected_trials": 1, "unknown_trials": 0, "reasons": []}}
        rows.append(row)
    ledger = RetentionLedger(tmp_path / "retention.sqlite", "independent-bridge", rows[0]["score_kind"])
    kept = merge_candidates(rows, 2, ledger=ledger, stage="coarse:0")
    kept = merge_candidates(kept, 2, ledger=ledger, stage="global:0")
    if case == "corrupt":
        with sqlite3.connect(ledger.path) as db:
            db.execute("DELETE FROM records WHERE score < -2")
    finite = ledger.evidence(kept, complete=True, spacing_m=1000., refine_spacing_m=100.,
                             max_event_groups=2, expected_stages={"coarse": 1, "global": 1})
    if case == "unassessed":
        kept[1]["scoring_assessment"].update(complete=False, unknown_trials=1)
    assessed = [r["mode_id"] for r in kept if classified_assessment(r)]
    search = {"ranked": kept, "status": "complete", "scoring_time_is_locked": True,
              "alternative_modes_exhaustively_assessed": False,
              "finite_search_evidence": finite, "core_assessed_mode_ids": assessed}
    state = {"coverage": {"search_complete": True, "data_status": "available", "limitations": []},
             "recording": {"time_window": {"start_utc": "2026-09-21T14:13:20Z",
                                           "end_utc": "2026-09-21T14:13:20Z", "source": "user"}}}
    before = deepcopy(search)

    def finish(status, reason_code, message, **fields):
        return dict(status=status, reason_code=reason_code, message=message, **fields)

    # Profiles are controlled inputs. This tests the boundary, not their physical
    # generation; disabling refinement avoids substituting mocks for that work.
    job_id = "abb7afeffda8451ba9cb1bd6f8d95707"
    output = tmp_path / "jobs" / job_id
    output.mkdir(parents=True)
    result = _decide(search, events, events, [], [], None, state, output,
                     {"refine_finalists": 0}, finish, lambda: None)
    artifact = json.loads((output / "decision.json").read_text())
    assert result["reason_code"] == reason
    assert result["status"] == ("succeeded" if case == "complete" else "inconclusive")
    assert artifact["candidates"] == result["candidates"]
    assert search == before
    if case == "complete":
        assert result["candidates"][0]["uncertainty"]["radius_m"] == pytest.approx(160.)
        assert result["candidates"][0]["uncertainty"]["method"] == "finite_mode_and_tested_profile_union"
        assert finite["discarded_count"] == 1
        assert finite["best_discarded_score"] == -5.
        assert result["candidates"][0]["lat"] == kept[0]["lat"]
        assert artifact["diagnostics"]["finite_search"]["continuous_space_uniqueness"] == "not established"
        wire = validate_result(dict(schema_version=1, job_id=job_id, status=result["status"],
                                    events=events, coverage=state["coverage"], candidates=result["candidates"],
                                    artifacts={"decision": "decision.json"}))
        (output / "result.json").write_text(json.dumps(wire))
        manager = JobManager(tmp_path / "jobs")
        server = JobServer(("127.0.0.1", 0), manager)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/jobs/{job_id}"
            with urlopen(url) as response:
                assert json.load(response) == wire
            with urlopen(url+"/artifacts/decision.json") as response:
                assert json.load(response) == artifact
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            manager.close()
