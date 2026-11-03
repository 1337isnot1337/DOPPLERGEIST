"""Recompute saved six-event scores at five fixed points, with no truth input."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    started = time.monotonic()
    audit = json.loads((root / "archive-audit.json").read_bytes())
    runtime_root = root / "frozen-runtime"
    for entry in audit["wheel"]["files"]:
        path = runtime_root / entry["path"].removeprefix("src/")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    sys.path.insert(0, str(runtime_root))
    import numpy as np
    from pyproj import Transformer
    from aircraft_geoloc.data_access import FlightIndex
    from aircraft_geoloc.geometry import ecef
    from aircraft_geoloc.matching import prepare_events, score_ridges, association_score
    from aircraft_geoloc.terrain import Terrain
    from aircraft_geoloc.tiled_search import merge_candidates

    evidence = root / "restored/verification"
    search = json.loads((evidence / "terminal-search-search-report.json").read_bytes())
    discovery = json.loads((evidence / "terminal-discovery-discovery.json").read_bytes())
    native = json.loads((evidence / "terminal-score-participation-check.json").read_bytes())
    rankings = json.loads((root / "coarse-rankings-for-replay.json").read_bytes())
    merged = merge_candidates([row for tile in rankings for row in tile], search["candidate_retention_limit"])
    assert merged == search["coarse_ranked"]
    events, measurements = prepare_events(discovery["events"])
    rows = search["ranked"]
    selected = rows[:1]
    full = next((row for row in rows if len(row.get("event_indices", [])) == len(events)), None)
    if full is not None and (not selected or full != selected[0]):
        selected.append(full)
    index = FlightIndex(root / "restored/derived-inputs/flights-runtime-v2.sqlite")
    terrain = Terrain([root / "canonical/inputs/terrain.tif"], geoid_path=root / "canonical/inputs/geoid.tif")
    time_ranges = [source["requested_time_range_s"] for source in search["data_coverage"]]
    assert time_ranges and all(times == time_ranges[0] for times in time_ranges)
    to_xy = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    to_ll = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)
    out = {"scope": "Frozen scorer at five fixed positions and the saved shared clock; source fits remain native. No discovery/search/refinement/decision rerun and no truth input.",
           "selection": "Leading search row, plus first all-group row if distinct; no label-based selection.",
           "checked_at_utc": datetime.now(timezone.utc).isoformat(),
           "runtime_commit": audit["runtime_commit"], "wheel_sha256": audit["wheel"]["sha256"],
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "python": platform.python_version(),
           "versions": {name: version(name) for name in ("numpy", "scipy", "pandas", "pyarrow", "pyproj", "rasterio")},
           "proposed_group_count": len(events), "coarse_remerge_exact": True,
           "coarse_record_count": len(merged), "candidate_checks": []}
    max_native_delta = 0.0
    assert len(selected) == len(native["candidate_checks"])
    for row, native_check in zip(selected, native["candidate_checks"]):
        indices = row.get("event_indices", list(range(len(events))))
        assert indices == native_check["event_indices"]
        assert row["flight_ids"] == native_check["flight_ids"]
        chosen_events = [events[i] for i in indices]
        chosen_measurements = [measurements[i] for i in indices]
        bounds = (row["lon"] - .7, row["lat"] - .7, row["lon"] + .7, row["lat"] + .7)
        tracks = {track.id: track for track in index.query(bounds, time_ranges[0])}
        chosen_tracks = [tracks[name] for name in row["flight_ids"]]
        x, y = to_xy.transform(row["lon"], row["lat"])
        evaluations = []
        for dx, dy in [(0, 0), (100, 0), (-100, 0), (0, 100), (0, -100)]:
            lon, lat = to_ll.transform(x + dx, y + dy)
            elevation = float(terrain.sample(np.array([lat]), np.array([lon]))[0])
            score = score_ridges(chosen_tracks, chosen_events, chosen_measurements,
                                 ecef(lat, lon, elevation), row["recording_start_time_s"])
            association = association_score(score, chosen_events)
            contributions = [association_score({"score": residual, "event_scores": [residual]}, [event])["score"]
                             for event, residual in zip(chosen_events, score["event_scores"])]
            assert len(contributions) == len(indices) and all(math.isfinite(value) for value in contributions)
            assert math.isclose(sum(contributions), association["score"], rel_tol=1e-12, abs_tol=1e-12)
            evaluations.append({"dx_m": dx, "dy_m": dy, "lat": lat, "lon": lon,
                                "shared_recording_start_s": row["recording_start_time_s"],
                                "raw_residual_score": score["score"], "raw_event_scores": score["event_scores"],
                                "normalized_group_contributions": contributions,
                                "association_score": association["score"]})
        for actual, expected in zip(evaluations, native_check["evaluations"]):
            for key in actual:
                a, b = np.asarray(actual[key]), np.asarray(expected[key])
                assert a.shape == b.shape
                delta = float(np.max(np.abs(a - b)))
                max_native_delta = max(max_native_delta, delta)
                assert np.allclose(a, b, rtol=1e-10, atol=1e-8), (key, delta)
        base = evaluations[0]
        residual_changes = [max(abs(item["raw_event_scores"][j] - base["raw_event_scores"][j])
                               for item in evaluations[1:]) for j in range(len(indices))]
        assert all(change > 0 for change in residual_changes)
        out["candidate_checks"].append({"event_indices": indices, "flight_ids": row["flight_ids"],
                                       "stored_search_score": row["score"],
                                       "recomputed_search_score": base["association_score"],
                                       "recomputed_score_difference": base["association_score"] - row["score"],
                                       "sum_of_group_contributions": sum(base["normalized_group_contributions"]),
                                       "all_group_contributions_finite": True,
                                       "max_event_residual_change_over_100m_offsets_hz": residual_changes,
                                       "evaluations": evaluations})
    out["max_absolute_difference_from_native_participation"] = max_native_delta
    out["elapsed_s"] = time.monotonic() - started
    (root / "participation-audit.json").write_text(json.dumps(out, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"candidate_checks": len(selected), "proposed_groups": len(events),
                      "max_native_delta": max_native_delta, "coarse_remerge_exact": True,
                      "elapsed_s": out["elapsed_s"]}))


if __name__ == "__main__":
    main()
