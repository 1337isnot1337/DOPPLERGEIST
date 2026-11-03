"""Validate previously discovered modes before using a fixed Top-K floor."""
import math

import numpy as np
import pandas as pd

from .data_access import DataUnavailable, content_hash
from .finite_search import classified_assessment
from .geometry import AcousticSupportError, ecef
from .matching import _cache_ridge_fits, association_candidates
from .search import cpa_table, score_candidate


@_cache_ridge_fits
def validate_bootstrap(document, indexes, terrain, events, measurements, bounds,
                       time_range, budget, parameters, filters, start_window, crs):
    """Rebuild every witness from actual tracks, receiver grid and clock search.

    A validated witness is a fully assessed association in the same coarse
    search domain. Distinctness excludes its best clock, so later clock
    optimization cannot collapse two witnesses into one mode.
    """
    from .tiled_search import (_association_clock_window, _expanded_bounds, _sample_tile_terrain,
                               _split_tile_cells, _tile_coordinates, grid_tiles)

    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or not isinstance(document.get("witnesses"), list)
            or len(document["witnesses"]) != budget.top_k):
        raise DataUnavailable("Bootstrap needs exactly Top-K witness inputs")
    if (parameters.get("mode") != "robust_ridge" or parameters.get("time_origin") is not None
            or filters.get("association") != "subsets" or filters.get("silence")
            or start_window is None):
        raise DataUnavailable("Bootstrap requires subset scoring, an unknown clock window, and no silence filter")
    witnesses = document["witnesses"]
    ids = set()
    for witness in witnesses:
        if not isinstance(witness, dict) or not isinstance(witness.get("flight_ids"), list):
            raise DataUnavailable("Malformed bootstrap witness")
        if any(not isinstance(fid, str) or not fid for fid in witness["flight_ids"]):
            raise DataUnavailable("Invalid bootstrap flight ID")
        ids.update(witness["flight_ids"])
    if len(ids) > budget.max_tracks_per_tile:
        raise DataUnavailable("Bootstrap flight lookup budget exceeded")
    tracks = {}
    for index in indexes:
        for track in index.lookup(sorted(ids), max_tracks=budget.max_tracks_per_tile,
                                  max_samples=budget.max_track_samples_per_tile):
            if track.id in tracks:
                raise DataUnavailable("Bootstrap flight ID is not unique across indexes")
            tracks[track.id] = track
    if ids != set(tracks):
        raise DataUnavailable("Bootstrap flight is missing from the indexed data")

    roots = grid_tiles(bounds, budget.spacing_m, budget.tile_cells, crs)
    if budget.max_tiles is not None:
        import itertools
        roots = itertools.islice(roots, budget.max_tiles)
    roots = dict(roots)
    center, tolerance = _association_clock_window(start_window, parameters.get("time_sweep_s", 5.0))
    radius = max(event["slant_range_m"][1] for event in events)
    sound_speed = parameters.get("c", 343.0)
    points_cache, cpa_cache, membership, ground_files, ocean_tiles = {}, {}, {}, set(), set()
    seen, validated, replay_inputs = set(), [], []
    for witness in witnesses:
        try:
            x, y = map(float, witness["position_m"])
            indices = witness["event_indices"]
            flight_ids = witness["flight_ids"]
            emissions = [float(value) for value in witness["pass_emission_times_s"]]
            if (not math.isfinite(x) or not math.isfinite(y) or not isinstance(indices, list)
                    or not indices or any(type(i) is not int or not 0 <= i < len(events) for i in indices)
                    or indices != sorted(set(indices)) or len(indices) != len(flight_ids)
                    or len(indices) != len(emissions) or not all(math.isfinite(t) for t in emissions)
                    or any(not time_range[0] <= t <= time_range[1] for t in emissions)):
                raise ValueError("invalid witness fields")
            ix, iy = round(x / budget.spacing_m), round(y / budget.spacing_m)
            if x != ix * budget.spacing_m or y != iy * budget.spacing_m:
                raise ValueError("receiver is not on the coarse grid")
            root_name = f"{ix // budget.tile_cells}_{iy // budget.tile_cells}"
            if root_name not in roots:
                raise ValueError("receiver lies outside the tile budget")
            position = (ix, iy)
            if position not in points_cache:
                points = _tile_coordinates((ix, iy, ix + 1, iy + 1), budget.spacing_m, bounds, crs)
                if len(points) != 1:
                    raise ValueError("receiver lies outside the search bounds")
                _sample_tile_terrain(points, terrain)
                ground_files.update(getattr(terrain, "last_sample_files", set()))
                ocean_tiles.update(getattr(terrain, "last_sample_ocean_tiles", set()))
                points_cache[position] = points
            points = points_cache[position]
            cells = roots[root_name]
            while True:
                needed = {fid for fid in flight_ids if (cells, fid) not in membership}
                if needed:
                    spatial = _expanded_bounds(cells, budget.spacing_m, radius, crs)
                    found = set().union(*(index.matching_names(needed, spatial, time_range) for index in indexes))
                    for fid in needed:
                        membership[cells, fid] = fid in found
                if any(not membership[cells, fid] for fid in flight_ids):
                    raise ValueError("flight is outside a possible spatial/time query")
                children = _split_tile_cells(cells)
                if not children:
                    break
                cells, = (part for part in children if part[0] <= ix < part[2] and part[1] <= iy < part[3])
            observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
            pass_rows = []
            for fid, emission in zip(flight_ids, emissions):
                key = (position, fid)
                if key not in cpa_cache:
                    if tracks[fid].outside_observer_radius(observers, radius, sound_speed):
                        raise ValueError("flight is outside the conservative receiver radius")
                    cpa_cache[key] = cpa_table([tracks[fid]], points, radius, sound_speed, budget.cpa_step_s)
                table = cpa_cache[key]
                matched = table[np.abs(table["emission_time"] - emission) < 1e-6]
                if len(matched) != 1:
                    raise ValueError("CPA pass was not uniquely reproduced")
                pass_rows.append(matched.iloc[0].to_dict())
            candidates, _ = association_candidates(
                pd.DataFrame(pass_rows), events, offset_tolerance_s=filters.get("offset_tolerance_s", 5.0),
                time_origin=center, time_tolerance_s=tolerance, min_events=filters.get("min_events", 1),
                max_events=filters.get("max_events") or len(events), max_candidates=budget.max_candidates_per_tile)
            matches = [candidate for candidate in candidates if candidate["event_indices"] == indices
                       and [row["flight_id"] for row in candidate["passes"]] == flight_ids
                       and all(abs(row["emission_time"]-t) < 1e-6
                               for row, t in zip(candidate["passes"], emissions))]
            if len(matches) != 1:
                raise ValueError("association was not uniquely reproduced")
            candidate = matches[0]
            lo, hi = candidate["recording_start_bounds_s"]
            sweep = parameters.get("time_sweep_s", 5.0)
            lo, hi = max(lo-sweep, start_window[0]), min(hi+sweep, start_window[1])
            if lo > hi:
                raise ValueError("association has no clock in the search window")
            candidate = dict(candidate, recording_start_bounds_s=[lo, hi])
            settings = dict(parameters, time_origin=None, time_sweep_s=0)
            row = score_candidate(candidate, points.iloc[0], tracks, events, measurements, **settings)
            if not classified_assessment(row) or not math.isfinite(row["score"]):
                raise ValueError("association is not completely assessed")
            canonical = {"position_m": [float(points.iloc[0].x), float(points.iloc[0].y)],
                         "event_indices": indices, "flight_ids": flight_ids,
                         "pass_emission_times_s": [float(item["emission_time"]) for item in candidate["passes"]]}
            key = content_hash(canonical)
            if key in seen:
                raise ValueError("duplicate association and receiver")
            seen.add(key)
            validated.append({"witness": canonical, "score": float(row["score"]),
                              "recording_start_time_s": float(row["recording_start_time_s"]),
                              "scoring_assessment": row["scoring_assessment"]})
            replay_inputs.append((candidate, points.iloc[0], settings))
        except (AcousticSupportError, KeyError, TypeError, ValueError, OverflowError) as error:
            raise DataUnavailable(f"Invalid bootstrap witness: {error}") from error
    floor = math.nextafter(min(item["score"] for item in validated), -math.inf)
    for item, (candidate, point, settings) in zip(validated, replay_inputs):
        try:
            row = score_candidate(candidate, point, tracks, events, measurements, score_floor=floor, **settings)
        except (AcousticSupportError, ValueError) as error:
            raise DataUnavailable(f"Bootstrap cutoff replay failed: {error}") from error
        if (not classified_assessment(row) or not math.isfinite(row["score"])
                or row["score"] < floor or row["score"] != item["score"]):
            raise DataUnavailable("Bootstrap witness score changed under its proposed floor")
        item["score_with_floor"] = float(row["score"])
        item["floor_scoring_assessment"] = row["scoring_assessment"]
    files = getattr(terrain, "files", {})
    return {"score_floor": floor, "witnesses": validated,
            "terrain_files": {name: files[name]["sha256"] for name in sorted(ground_files)},
            "terrain_ocean_tiles": sorted(ocean_tiles)}
