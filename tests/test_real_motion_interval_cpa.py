"""Localized CPA checks on unchanged released ADS-B and measured audio inputs.

Receiver hypotheses and clock bounds are the existing development workload,
not microphone-location truth. No aircraft samples or audio are generated.
"""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import minimize_scalar

from dopplergeist.geometry import AcousticSupportError, Track, ecef
from dopplergeist.matching import prepare_events
from dopplergeist.search import _PreparedCPATrack, _ordered_cpa_rows, cpa_table_dense
from dopplergeist.tracks import load_tracks


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real_intervals():
    root = Path(os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT", ROOT))
    source = root / "data/adsb/2026-09-08/reference-region.parquet"
    if not source.is_file():
        pytest.skip("restore the real reference archive or set DOPPLERGEIST_REAL_REFERENCE_ROOT")
    workload = json.loads((ROOT / "tests/data/real-search-workloads.json").read_text())
    tracks, _ = load_tracks(source)
    cases = []
    for name, case in workload["cases"].items():
        points = pd.DataFrame([case["point"]])
        observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
        admitted, unknown = [], []
        for track in tracks:
            try:
                if track.outside_observer_radius(observers, 20000., 343.):
                    continue
            except AcousticSupportError:
                pass
            else:
                continue
            try:
                prepared = _PreparedCPATrack(track, 343., 2., motion_observers=observers, max_distance=20000.)
            except AcousticSupportError:
                unknown.append(track)
            else:
                admitted.append(prepared)
        assert admitted and unknown
        cases.append((name, points, observers, admitted, unknown))
    return workload, tracks, cases


def rows(prepared, observers):
    return _ordered_cpa_rows(prepared.raw_rows(observers, np.arange(len(observers)), 20000.), 2.)


def test_real_local_cpa_preserves_original_lattice_and_every_proposal(real_intervals):
    _, tracks, cases = real_intervals
    summary = []
    for name, _, observers, admitted, unknown in cases:
        count = nonempty = multiple = 0
        for prepared in admitted:
            track = prepared.track
            original_time = track.time.copy()
            expected_lattice = np.unique(np.r_[np.arange(track.time[0], track.time[-1], 2.), track.time[-1]])
            assert np.array_equal(prepared.time, expected_lattice)
            actual = rows(prepared, observers)
            # Diagnostic arithmetic reference only. The interval proof above,
            # not bypassing this validator, supplies physical CPA support.
            with patch.object(Track, "validate_motion_support", lambda *args: None):
                previous = _PreparedCPATrack(track, 343., 2.)
                expected = rows(previous, observers)
            assert actual == expected
            assert prepared.max_step == previous.max_step
            assert np.array_equal(track.time, original_time)
            count += len(actual)
            nonempty += bool(actual)
            multiple += len(prepared.motion_support["emission_intervals_s"]) > 1
        assert count > 0 and nonempty > 0 and multiple > 0
        summary.append({"case": name, "admitted": len(admitted), "unresolved": len(unknown),
                        "cpa_rows": count, "nonempty_tracks": nonempty})
    # Clean sources keep the same path and do not acquire an exclusion receipt.
    clean_checked = 0
    for track in tracks:
        try:
            old = _PreparedCPATrack(track, 343., 2.)
        except AcousticSupportError:
            continue
        expected = rows(old, cases[0][2])
        if not expected:
            continue
        local = _PreparedCPATrack(track, 343., 2., motion_observers=cases[0][2], max_distance=20000.)
        assert local.motion_support is None
        assert rows(local, cases[0][2]) == expected
        clean_checked += 1
        if clean_checked == 5:
            break
    assert clean_checked == 5
    print(json.dumps({"exact_sparse_cpa": summary, "clean_controls": clean_checked}))


def test_real_dense_comparison_keeps_existing_sampling_limits_visible(real_intervals):
    _, _, cases = real_intervals
    summary = []
    for name, points, observers, admitted, _ in cases:
        count = dense_count = fine_count = 0
        largest_time = largest_range = 0.
        for prepared in admitted:
            actual = rows(prepared, observers)
            with patch.object(Track, "validate_motion_support", lambda *args: None):
                dense = cpa_table_dense([prepared.track], points, 20000., c=343., step_s=2.)
                fine = prepared.track.closest_approaches(observers[0], max_distance=20000., c=343., step=.125)
            count += len(actual)
            dense_count += len(dense)
            fine_count += len(fine)
            for row in actual:
                assert fine
                closest = min(fine, key=lambda value: abs(value["emission_time"]-row[2]))
                delta_time = abs(closest["emission_time"]-row[2])
                delta_range = abs(closest["distance_m"]-row[4])
                # Sparse CPA deliberately projects its two-second lattice.
                # Compare with a finer continuous-spline solve without claiming
                # that the existing finite proposer finds every narrow minimum.
                assert delta_time < 2. * 1.1
                assert delta_range < 343. * 2.
                largest_time, largest_range = max(largest_time, delta_time), max(largest_range, delta_range)
        assert count and dense_count and fine_count
        summary.append({"case": name, "sparse_rows": count, "dense_2s_rows": dense_count,
                        "continuous_0_125s_minima": fine_count, "max_time_difference_s": largest_time,
                        "max_range_difference_m": largest_range})
    print(json.dumps({"independent_dense_comparison": summary}))


def test_real_first_and_final_sample_intervals_remain_intact(real_intervals):
    _, tracks, cases = real_intervals
    # These complete observed tracks have endpoint-adjacent minima at the
    # workload's existing receiver hypotheses. No trajectory is cut or shifted.
    controls = (("previous-fit", "a46d03:38", False),
                ("previous-fit", "a740a3:3", True), ("offset", "ad6cf9:2", False))
    for name, identity, final in controls:
        observers = next(case[2] for case in cases if case[0] == name)
        track = next(track for track in tracks if track.id == identity)
        prepared = _PreparedCPATrack(track, 343., 2., motion_observers=observers, max_distance=20000.)
        assert prepared.motion_support is None
        lo, hi = prepared.time[-2:] if final else prepared.time[:2]
        reference = minimize_scalar(lambda dt: np.sum((track.position(lo+dt)-observers[0])**2),
                                    bounds=(0., hi-lo), method="bounded", options={"xatol": .0001})
        assert reference.success and 0 < reference.x < hi-lo and reference.fun < 20000.**2
        matches = [row for row in rows(prepared, observers) if lo < row[2] < hi]
        assert len(matches) == 1
        assert abs(matches[0][2]-(lo+reference.x)) < .001
        assert abs(matches[0][4]-np.sqrt(reference.fun)) < .01
    print(json.dumps({"observed_endpoint_controls": {"first": 2, "final": 1}}))


def test_real_unproven_boundaries_and_query_changes_fail_closed(real_intervals):
    _, _, cases = real_intervals
    for _, _, observers, admitted, unknown in cases:
        for track in unknown:
            with pytest.raises(AcousticSupportError) as original:
                track.validate_motion_support(343.)
            with pytest.raises(AcousticSupportError) as scoped:
                _PreparedCPATrack(track, 343., 2., motion_observers=observers, max_distance=20000.)
            assert vars(scoped.value) == vars(original.value)
        prepared = admitted[0]
        proof = prepared.motion_support
        # Exercise equality at the outward-rounded hull bound using the same
        # observed spline and receiver, not altered aircraft observations.
        with pytest.raises(AcousticSupportError):
            _PreparedCPATrack(prepared.track, 343., 2., motion_observers=observers,
                              max_distance=proof["hull_distance_lower_m"])
        with pytest.raises(AcousticSupportError):
            prepared.raw_rows(observers, np.array([0]), 20001.)
        other = cases[1 if cases[0][2] is observers else 0][2]
        with pytest.raises(AcousticSupportError):
            prepared.raw_rows(other, np.array([0]), 20000.)
        # Alternate sound speeds must recheck the native intervals.
        changed = _PreparedCPATrack(prepared.track, 333.3, 2., motion_observers=observers, max_distance=20000.)
        assert changed.motion_support["sound_speed_mps"] == 333.3


def test_real_acoustic_unknown_arrivals_survive_local_cpa_support(real_intervals):
    _, _, cases = real_intervals
    for _, _, observers, admitted, _ in cases:
        prepared = admitted[0]
        first, last = prepared.motion_support["emission_intervals_s"][0]
        emission = first + (last-first)/2
        receive = emission + np.linalg.norm(prepared.track.position(emission)-observers[0])/343.
        with pytest.raises(AcousticSupportError) as supported:
            prepared.track._check_motion_support(np.array([receive]), observers[0], 343.)
        assert [first, last] in supported.value.emission_intervals_s
        with pytest.raises(AcousticSupportError):
            prepared.track.acoustic(np.array([receive]), observers[0], 343.)
        with pytest.raises(AcousticSupportError):
            prepared.track.validate_motion_support(343.)


def test_real_recovered_cpa_supports_acoustic_and_measured_hypotheses(real_intervals):
    from dopplergeist.tiled_search import SearchBudget, _score

    workload, _, cases = real_intervals
    acoustic_counts = []
    for name, _, observers, admitted, _ in cases:
        count = 0
        for prepared in admitted:
            proposals = rows(prepared, observers)
            if not proposals:
                continue
            receive = np.asarray([row[3] for row in proposals])
            factor, emission, distance = prepared.track.acoustic(receive, observers[0], 343.)
            assert np.isfinite([factor, emission, distance]).all()
            residual = emission + np.linalg.norm(prepared.track.position(emission)-observers[0], axis=1)/343. - receive
            assert np.all(np.abs(residual) <= np.maximum(1e-7, 4*np.abs(np.spacing(receive))))
            count += len(proposals)
        assert count
        acoustic_counts.append({"case": name, "supported_cpa_arrivals": count})

    # Use the very track recovered in the limited-clock regression below. The
    # ordinary free-clock generator aligns unchanged measured ridges to its two
    # actual CPA proposals. This component check supplies no recording-clock or
    # location truth; the original limited-clock result remains separate.
    _, points, _, admitted, _ = next(case for case in cases if case[0] == "offset")
    track = next(prepared.track for prepared in admitted if prepared.track.id == "ad340b:8")
    events, measurements = prepare_events(workload["events"])
    args = (points, [track], events, measurements, SearchBudget(**workload["budget"]), workload["scoring"], {})
    actual, counts = _score(*args)
    assert actual and all(np.isfinite(row["score"]) and row["flight_ids"] == [track.id] for row in actual)
    assert any(row["core_assessment_complete"] for row in actual)
    assert counts["evaluated_trials"] > 0 and counts["unknown_trials"] > 0
    assert counts["unclassified_candidate_assessments"]
    assert [item["track_id"] for item in counts["interval_supported_cpa_tracks"]] == [track.id]
    # Diagnostic comparison changes only the global CPA gate. Original acoustic
    # motion/arrival guards still classify every clock trial on both paths.
    with patch.object(Track, "validate_motion_support", lambda *args: None):
        expected, expected_counts = _score(*args)
    expected_counts["interval_supported_cpa_tracks"] = counts["interval_supported_cpa_tracks"]
    assert actual == expected and counts == expected_counts
    print(json.dumps({"recovered_acoustic_components": {"cpa_arrivals": acoustic_counts,
        "free_clock_associations": counts["candidates"], "finite_hypotheses": len(actual),
        "evaluated_trials": counts["evaluated_trials"], "rejected_trials": counts["rejected_trials"],
        "unknown_trials": counts["unknown_trials"], "exact_diagnostic_parity": True}}))


def verifier():
    spec = importlib.util.spec_from_file_location("verify_interval_cpa", ROOT / "scripts/verify_upload_http.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_interval_receipts_reject_corrupted_inequalities(real_intervals):
    workload, _, cases = real_intervals
    check = verifier().valid_interval_cpa_support
    events, _ = prepare_events(workload["events"])
    config = {"events": events, "scoring": workload["scoring"], "budget": workload["budget"]}
    for _, _, _, admitted, _ in cases:
        for prepared in admitted:
            proof = prepared.motion_support
            assert check(proof, config)
            for key, value in (("hull_distance_lower_m", proof["max_distance_m"]),
                               ("edge_distance_lower_m", proof["query_radius_m"]),
                               ("query_radius_m", proof["max_distance_m"]),
                               ("sound_speed_mps", 333.3), ("sample_step_s", 3.),
                               ("receiver_point_count", 0), ("emission_intervals_s", [])):
                assert not check({**proof, key: value}, config)
            damaged = deepcopy(proof)
            damaged["observer_box_ecef_m"][0][0] = damaged["observer_box_ecef_m"][1][0] + 1
            assert not check(damaged, config)


def test_real_interval_proof_overhead(real_intervals):
    _, _, cases = real_intervals
    comparisons = []
    for name, _, observers, admitted, _ in cases:
        original_times, local_times = [], []
        for repetition in range(3):
            for local in ((False, True) if repetition % 2 == 0 else (True, False)):
                began = time.process_time()
                for previous in admitted:
                    track = previous.track
                    if local:
                        prepared = _PreparedCPATrack(track, 343., 2., motion_observers=observers, max_distance=20000.)
                    else:
                        with patch.object(Track, "validate_motion_support", lambda *args: None):
                            prepared = _PreparedCPATrack(track, 343., 2.)
                    rows(prepared, observers)
                (local_times if local else original_times).append(time.process_time()-began)
        comparisons.append({"case": name, "track_receiver_pairs": len(admitted),
                            "original_diagnostic_cpu_s": float(np.median(original_times)),
                            "local_proof_cpu_s": float(np.median(local_times))})
    print(json.dumps({"warm_cpa_overhead": comparisons}))


def test_real_measurements_preserve_nonempty_ranking_and_unknown_work(real_intervals, tmp_path):
    from dopplergeist.data_access import FlightIndex
    from dopplergeist.finite_search import RetentionLedger
    from dopplergeist.tiled_search import SearchBudget, _record_support, _score

    path = os.environ.get("DOPPLERGEIST_REAL_FLIGHT_INDEX")
    if not path or not Path(path).is_file():
        pytest.skip("set DOPPLERGEIST_REAL_FLIGHT_INDEX to the restored reference-region index")
    workload, _, _ = real_intervals
    case = workload["cases"]["offset"]
    index = FlightIndex(path)
    assert [{key: value[key] for key in ("sha256", "bytes")} for value in index.report["sources"]] == workload["index_identity"]["sources"]
    tracks = list(index.query(case["query_bounds"], workload["query_time_s"]))
    events, measurements = prepare_events(workload["events"])
    points = pd.DataFrame([case["point"]])
    args = (points, tracks, events, measurements, SearchBudget(**workload["budget"]),
            workload["scoring"], {}, workload["recording_start_window_s"])
    ledgers = {name: RetentionLedger(tmp_path / f"{name}.sqlite", "real-motion-interval-cpa",
                                    "matched_group_support_minus_normalized_residual")
               for name in ("actual", "baseline", "diagnostic")}
    stage = "coarse:observed"
    actual, counts = _score(*args, ledger=ledgers["actual"], stage=stage)
    selected = {item["track_id"] for item in counts["interval_supported_cpa_tracks"]}
    assert actual and selected and counts["unknown_trials"] > 0
    with patch.object(Track, "_cpa_interval_exclusion", return_value=None):
        old, old_counts = _score(*args, ledger=ledgers["baseline"], stage=stage)
    assert actual == old
    assert counts["cpa_rows"] > old_counts["cpa_rows"]
    assert {item["track_id"] for item in old_counts["unsupported_cpa_tracks"]} == (
        {item["track_id"] for item in counts["unsupported_cpa_tracks"]} | selected)
    assert counts["unknown_trials"] == old_counts["unknown_trials"]
    assert counts["unclassified_candidate_assessments"] == old_counts["unclassified_candidate_assessments"]

    original = Track.validate_motion_support
    def diagnostic_validate(track, c=343.):
        if track.id not in selected:
            original(track, c)
    with patch.object(Track, "validate_motion_support", diagnostic_validate):
        expected, expected_counts = _score(*args, ledger=ledgers["diagnostic"], stage=stage)
    assert actual == expected
    expected_counts["interval_supported_cpa_tracks"] = counts["interval_supported_cpa_tracks"]
    assert counts == expected_counts

    persisted = []
    for ledger in ledgers.values():
        checksum = ledger.checksum(stage)
        assert checksum and ledger.stage_valid(stage, checksum)
        with ledger.connect() as db:
            persisted.append((db.execute("SELECT * FROM records ORDER BY stage,mode_id").fetchall(),
                              db.execute("SELECT * FROM bounds ORDER BY stage,bound_id").fetchall(),
                              db.execute("SELECT * FROM stages ORDER BY name").fetchall()))
    assert persisted[0] == persisted[1] == persisted[2]
    assert persisted[0][0] and persisted[0][1]

    summary = dict.fromkeys(("unsupported_cpa_track_evaluations", "unclassified_score_candidates",
        "bounded_score_candidates", "unbounded_score_candidates", "evaluated_trials", "rejected_trials",
        "unknown_trials", "unreported_trial_envelopes"), 0)
    _record_support(tmp_path, stage, counts, summary)
    saved = json.loads((tmp_path / "support/coarse-observed.json").read_text())
    assert saved["interval_supported_cpa_tracks"] == counts["interval_supported_cpa_tracks"]
    assert summary["interval_supported_cpa_track_evaluations"] == len(selected)
    config = {"events": events, "scoring": workload["scoring"], "budget": workload["budget"]}
    assert all(verifier().valid_interval_cpa_support(item, config) for item in saved["interval_supported_cpa_tracks"])
    print(json.dumps({"real_measured_scoring": {"tracks": len(tracks), "retained": len(actual),
        "previous_cpa_rows": old_counts["cpa_rows"], "current_cpa_rows": counts["cpa_rows"],
        "candidates": counts["candidates"], "remaining_unknown_trials": counts["unknown_trials"],
        "interval_supported": len(selected), "retained_ledger_modes": len(persisted[0][0]),
        "retained_unknown_bounds": len(persisted[0][1]), "exact_ranking_and_ledger": True}}))
