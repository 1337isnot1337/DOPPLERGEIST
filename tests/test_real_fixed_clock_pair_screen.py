"""Fixed-clock event-pair screening check against the uploaded real recording."""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from dopplergeist import matching, tiled_search
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.matching import prepare_events
from dopplergeist.tracks import load_tracks


def test_real_fixed_clock_screen_preserves_retained_modes(monkeypatch, tmp_path):
    root = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT")
    discovery_path = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_DISCOVERY")
    if not root or not discovery_path:
        pytest.skip("set the real reference root and uploaded-audio discovery paths")
    root, discovery_path = Path(root), Path(discovery_path)
    reference = json.loads((root / "results/reference-local/ranked.json").read_text())[0]
    clock = reference["recording_start_time_s"]
    detected = json.loads(discovery_path.read_text())["events"]
    events, measurements = prepare_events(detected)
    tracks, _ = load_tracks(root / "data/adsb/2026-09-08/reference-region.parquet",
                            time_range=(clock - 120, clock + 3720))
    points = pd.DataFrame([{key: reference[key] for key in
                            ("point_id", "lat", "lon", "elev_m", "x", "y")}])
    parameters = {"mode": "robust_ridge", "time_origin": clock, "time_sweep_s": 0}
    filters = {"association": "subsets", "offset_tolerance_s": 5, "time_tolerance_s": 5}
    original = matching.association_candidates

    def run(name, disable_screen):
        if disable_screen:
            def unfiltered(*args, **kwargs):
                kwargs.pop("pair_screen", None)
                return original(*args, **kwargs)
            monkeypatch.setattr(matching, "association_candidates", unfiltered)
        else:
            monkeypatch.setattr(matching, "association_candidates", original)
        ledger = RetentionLedger(tmp_path / f"{name}.sqlite", "real-fixed-clock-pair-screen",
                                 "matched_group_support_minus_normalized_residual")
        return tiled_search._score(points, tracks, events, measurements, tiled_search.SearchBudget(),
                                   parameters, filters, ledger=ledger, stage="coarse:real-fixed-clock")

    baseline, baseline_counts = run("baseline", True)
    screened, counts = run("screened", False)
    evidence = counts["fixed_clock_event_pair_screen"]
    assert baseline == screened
    assert baseline_counts["candidates"] == 575
    assert counts["candidates"] == 95
    assert evidence["checked"] == 10 and evidence["rejected"] == 3
    assert not evidence["unknown"] and not evidence["budget_exhausted"]
    assert all(row["support_fraction"] == 1.0 and row["reason"] == "association_residual_limit"
               and -row["event_score_hz"] > row["residual_limit_hz"]
               for row in evidence["rejections"])
    support = tmp_path / "support-output"
    support.mkdir()
    summary = {key: 0 for key in ("unsupported_cpa_track_evaluations", "unclassified_score_candidates",
                  "bounded_score_candidates", "unbounded_score_candidates", "evaluated_trials",
                  "rejected_trials", "unknown_trials", "unreported_trial_envelopes")}
    tiled_search._record_support(support, "coarse:real-fixed-clock", counts, summary)
    receipt = support / "support/coarse-real-fixed-clock-event-pair-screen.json"
    persisted = json.loads(receipt.read_text())
    assert persisted["rejections"] == evidence["rejections"]
    assert summary["fixed_clock_event_pairs_rejected"] == 3
