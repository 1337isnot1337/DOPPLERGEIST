"""Sequential, checkpointed national search over one global projected grid.

Only the receiver grid is partitioned. Every tile sees all overlapping original
flight segments and the same event clocks, propagation model and scoring units.
"""
from dataclasses import asdict, dataclass
import itertools
import json
import math
from pathlib import Path
import resource
import time

import numpy as np
import pandas as pd
from pyproj import Transformer

from .data_access import CONUS, DataUnavailable, content_hash, sha256, write_json
from .search import cpa_table, filter_event, pair_candidates, score_candidate


@dataclass(frozen=True)
class SearchBudget:
    spacing_m: float = 2000.0
    tile_cells: int = 32
    max_tracks_per_tile: int = 2000
    max_track_samples_per_tile: int = 500000
    max_cpa_rows: int = 100000
    max_candidates_per_tile: int = 20000
    top_k: int = 100
    refine_spacing_m: float = 100.0
    refine_finalists: int = 10
    cpa_step_s: float = 2.0
    max_tiles: int | None = None

    def __post_init__(self):
        integer_fields = ("tile_cells", "max_tracks_per_tile", "max_track_samples_per_tile", "max_cpa_rows",
                          "max_candidates_per_tile", "top_k", "refine_finalists", "max_tiles")
        for name, value in asdict(self).items():
            if value is not None and (not np.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be positive and finite")
            if name in integer_fields and value is not None and type(value) is not int:
                raise ValueError(f"{name} must be an integer")
        if self.tile_cells > 256:
            raise ValueError("tile_cells must be <=256 (65536 grid points)")


def _key(row):
    # Distinct approaches remain distinct even when they share flight IDs.
    return (tuple(row.get("event_indices", range(len(row["flight_ids"])))), tuple(row["flight_ids"]),
            tuple(round(t, 3) for t in row.get("pass_emission_times_s", [])),
            round(row["x"], 6), round(row["y"], 6), round(row["recording_start_time_s"], 6))


def merge_candidates(rows, top_k):
    unique = {}
    for row in rows:
        if not math.isfinite(row["score"]):
            continue
        key = _key(row)
        if key not in unique or row["score"] > unique[key]["score"]:
            unique[key] = row
    return sorted(unique.values(), key=lambda row: (-row["score"], _key(row)))[:top_k]


def _grid_extent(bounds, spacing_m, crs):
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    left, bottom, right, top = forward.transform_bounds(*bounds, densify_pts=101)
    xmin, ymin = math.floor(left / spacing_m), math.floor(bottom / spacing_m)
    xmax, ymax = math.ceil(right / spacing_m), math.ceil(top / spacing_m)
    return xmin, ymin, xmax, ymax


def grid_tiles(bounds, spacing_m, tile_cells, crs="EPSG:5070"):
    """Half-open integer-cell cores: each global receiver cell has one owner."""
    xmin, ymin, xmax, ymax = _grid_extent(bounds, spacing_m, crs)
    for iy in range(ymin // tile_cells, ymax // tile_cells + 1):
        for ix in range(xmin // tile_cells, xmax // tile_cells + 1):
            yield f"{ix}_{iy}", (max(xmin, ix * tile_cells), max(ymin, iy * tile_cells),
                                  min(xmax + 1, (ix + 1) * tile_cells), min(ymax + 1, (iy + 1) * tile_cells))


def tile_points(cells, spacing, bounds, terrain, crs):
    x0, y0, x1, y1 = cells
    x, y = np.meshgrid(np.arange(x0, x1, dtype=np.int64), np.arange(y0, y1, dtype=np.int64))
    x, y = x.ravel() * spacing, y.ravel() * spacing
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(x, y)
    keep = (lon >= bounds[0]) & (lon <= bounds[2]) & (lat >= bounds[1]) & (lat <= bounds[3])
    x, y, lat, lon = (a[keep] for a in (x, y, lat, lon))
    return pd.DataFrame({"point_id": np.arange(len(x)), "x": x, "y": y, "lat": lat, "lon": lon,
                         "elev_m": terrain.sample(lat, lon) if len(lat) else np.array([])})


def _expanded_bounds(cells, spacing, radius, crs):
    x0, y0, x1, y1 = cells
    # Padding includes sound range, spline excursions between gap-limited track
    # samples and CONUS projection distortion. Full payloads remain unmodified.
    margin = 1.6 * radius + 15000
    box = (x0 * spacing - margin, y0 * spacing - margin, x1 * spacing + margin, y1 * spacing + margin)
    return Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform_bounds(*box, densify_pts=101)


def _tracks(indexes, bounds, time_range, budget):
    tracks, identities, samples = [], set(), 0
    for index in indexes:
        for track in index.query(bounds, time_range):
            # Same track from overlapping daily/source coverage must be identical;
            # silently dropping different geometry would change the physics.
            if track.id in identities:
                signature = content_hash([track.id, track.time.tolist(), track.xyz.tolist(), track.spline.c.tolist()])
                previous = next(t for t in tracks if t.id == track.id)
                if signature != content_hash([previous.id, previous.time.tolist(), previous.xyz.tolist(), previous.spline.c.tolist()]):
                    raise DataUnavailable(f"Conflicting flight segment identity: {track.id}")
                continue
            identities.add(track.id)
            tracks.append(track)
            samples += len(track.time)
            if len(tracks) > budget.max_tracks_per_tile or samples > budget.max_track_samples_per_tile:
                raise DataUnavailable("Tile track/sample memory budget exceeded; reduce tile_cells")
    return tracks


def _score(points, tracks, events, measurements, budget, parameters, filters, start_window=None):
    radius = max(e["slant_range_m"][1] for e in events)
    tables, count = [], 0
    # Bound materialized CPA rows before pairing; one track at a time keeps the
    # national traffic count out of the CPA tensor/list allocation.
    for track in tracks:
        samples = math.ceil((track.time[-1] - track.time[0]) / budget.cpa_step_s) + 1
        if samples > budget.max_track_samples_per_tile:
            raise DataUnavailable("CPA time-sampling memory budget exceeded")
        # Even a pathological looping track cannot allocate an unbounded list
        # of minima before we inspect the returned table.
        chunk_points = max(1, budget.max_cpa_rows // samples)
        for first in range(0, len(points), chunk_points):
            table = cpa_table([track], points.iloc[first:first + chunk_points], radius, parameters.get("c", 343.0), budget.cpa_step_s)
            count += len(table)
            if count > budget.max_cpa_rows:
                raise DataUnavailable("Tile CPA-row memory budget exceeded")
            if len(table):
                tables.append(table)
    if not tables:
        return [], {"cpa_rows": 0, "candidates": 0}
    table = pd.concat(tables, ignore_index=True)
    kwargs = dict(offset_tolerance_s=filters.get("offset_tolerance_s", 5.0),
                  time_origin=parameters.get("time_origin"), time_tolerance_s=filters.get("time_tolerance_s", 5.0),
                  silence=filters.get("silence"))
    subset = filters.get("association", "subsets" if parameters.get("mode") == "robust_ridge" else "full") == "subsets"
    if subset:
        from .matching import association_candidates
        candidates, counts = association_candidates(table, events, **kwargs,
            min_events=filters.get("min_events", 1), max_events=filters.get("max_events") or len(events),
            max_candidates=budget.max_candidates_per_tile)
    else:
        per_event = [filter_event(table, e, kwargs["time_origin"], kwargs["time_tolerance_s"]).groupby("point_id").size().to_dict() for e in events]
        upper = sum(math.prod(g.get(p, 0) for g in per_event) for p in points.point_id)
        if upper > budget.max_candidates_per_tile:
            raise DataUnavailable("Tile candidate memory budget exceeded; reduce tile_cells")
        candidates, counts = pair_candidates(table, events, **kwargs)
    # Attach approach identities before scoring, since legacy rank drops passes.
    ranked = []
    lookup = {row.point_id: row for row in points.itertuples()}
    track_lookup = {track.id: track for track in tracks}
    for candidate in candidates:
        settings = dict(parameters)
        scoring_candidate = candidate
        if start_window:
            if start_window[0] == start_window[1] and settings.get("time_origin") is None:
                settings["time_origin"] = start_window[0]
            anchor = settings.get("time_origin")
            if anchor is None:
                anchor_event = candidate.get("event_indices", [0])[0]
                anchor = candidate["passes"][0]["receive_time"] - events[anchor_event]["cpa_receive_s"]
            sweep = settings.get("time_sweep_s", 5.0)
            lower, upper = candidate.get("recording_start_bounds_s", (anchor, anchor))
            lo, hi = max(lower - sweep, start_window[0]), min(upper + sweep, start_window[1])
            if settings.get("time_origin") is not None:
                lo, hi = max(lo, anchor-sweep), min(hi, anchor+sweep)
            if lo > hi:
                continue
            if "event_indices" in candidate:
                scoring_candidate = dict(candidate, recording_start_bounds_s=[lo, hi])
                settings.update(time_origin=None, time_sweep_s=0)
            else:
                settings.update(time_origin=(lo + hi) / 2, time_sweep_s=(hi - lo) / 2)
        row = score_candidate(scoring_candidate, lookup[candidate["point_id"]], track_lookup, events, measurements, **settings)
        row["pass_emission_times_s"] = [float(p["emission_time"]) for p in candidate["passes"]]
        ranked.append(row)
    return merge_candidates(ranked, budget.top_k), dict(counts, cpa_rows=count, candidates=len(candidates))


def search_national(indexes, terrain, events, measurements, *, time_range_s, output_dir,
                    bounds=CONUS, budget=None, scoring=None, filters=None, crs="EPSG:5070", input_hashes=None):
    """Bounded outer driver using existing physical CPA/locked-event scoring.

    `events, measurements` come from `matching.prepare_events`. `time_range_s`
    is the absolute *emission* data query window, expanded for sound travel and
    the complete uncertain recording clock. `scoring.time_origin` is either a
    trusted fixed clock or None; it is never set independently per tile/event.
    A clock range can additionally constrain `recording_start_time_s` globally.
    """
    budget = budget or SearchBudget()
    if not indexes or not events or len(events) != len(measurements):
        raise ValueError("Supply flight indexes and one measurement per event")
    for e in events:
        if not 0 < e["slant_range_m"][1] < 1000000:
            raise ValueError("Event slant range must be finite and <1000 km")
    parameters = dict(scoring or {})
    start_window = parameters.pop("recording_start_window_s", None)
    if start_window and start_window[0] == start_window[1] and parameters.get("time_origin") is None:
        parameters["time_origin"] = start_window[0]
    filters = dict(filters or {})
    filters.setdefault("association", "subsets" if parameters.get("mode") == "robust_ridge" else "full")
    if filters["association"] not in ("subsets", "full"):
        raise ValueError("association must be 'subsets' or 'full'")
    event_limit = filters.get("max_events")
    if event_limit is None:
        event_limit = len(events)
    if type(event_limit) is not int or event_limit < 1:
        raise ValueError("max_events must be a positive integer or None for all groups")
    if filters["association"] == "full":
        event_limit = len(events)
    event_limit_applied = filters["association"] == "subsets" and event_limit < len(events)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    # Include actual acoustic measurements and implementation files in resume
    # identity; a detector/scorer change must never reuse stale tile scores.
    acoustic = []
    for spec, ridge, weight, fit in measurements:
        acoustic.append([hashlib_array(a) for a in [spec.time, getattr(spec, "frequency", []),
                                                   getattr(spec, "contrast", []), ridge, weight]])
    modules = {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    if hasattr(terrain, "files"):
        terrain_signature = {name: value["sha256"] for name, value in terrain.files.items()
                             if name in ("tileList.txt", terrain.geoid_path.name)}
    else:
        rasters = list(getattr(terrain, "rasters", []))
        if getattr(terrain, "geoid", None):
            rasters += terrain.geoid.rasters
        terrain_signature = {"constant_m": getattr(terrain, "constant", None),
                             "rasters": {str(r.name): sha256(r.name) for r in rasters}}
    identity = {"indexes": [{"input_hash": i.report["input_hash"], "file_sha256": sha256(i.path)} for i in indexes],
                "terrain": terrain_signature, "additional_input_hashes": input_hashes or {},
                "events": events, "acoustic_hashes": acoustic, "bounds": list(bounds), "time_range_s": list(time_range_s),
                "budget": asdict(budget), "scoring": scoring or {}, "filters": filters, "crs": crs, "code": modules}
    run_hash = content_hash(identity)
    manifest = output / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text())["run_hash"] != run_hash:
        raise DataUnavailable("Checkpoint configuration/input/implementation mismatch; use a new output directory")
    write_json(manifest, {"run_hash": run_hash, "configuration": identity})
    began, ranked, failures, done, resumed, points_searched = time.monotonic(), [], [], 0, 0, 0
    xmin, ymin, xmax, ymax = _grid_extent(bounds, budget.spacing_m, crs)
    total = (xmax // budget.tile_cells - xmin // budget.tile_cells + 1) * (ymax // budget.tile_cells - ymin // budget.tile_cells + 1)
    radius = max(e["slant_range_m"][1] for e in events)
    for number, (tile_id, cells) in enumerate(grid_tiles(bounds, budget.spacing_m, budget.tile_cells, crs)):
        if budget.max_tiles is not None and number >= budget.max_tiles:
            break
        checkpoint = output / f"tile-{tile_id}.json"
        try:
            if checkpoint.exists():
                record = json.loads(checkpoint.read_text())
                if record["run_hash"] != run_hash or record["payload_hash"] != content_hash(record["payload"]):
                    raise DataUnavailable("Corrupt tile checkpoint")
                payload = record["payload"]
                for source in payload.get("terrain_files", []):
                    if sha256(source["path"]) != source["sha256"]:
                        raise DataUnavailable("Terrain changed since tile checkpoint")
                resumed += 1
            else:
                tracks = _tracks(indexes, _expanded_bounds(cells, budget.spacing_m, radius, crs), time_range_s, budget)
                points = tile_points(cells, budget.spacing_m, bounds, terrain, crs) if tracks else pd.DataFrame()
                rows, counts = _score(points, tracks, events, measurements, budget, parameters, filters, start_window) if len(points) else ([], {})
                used = getattr(terrain, "last_sample_files", set()) if len(points) else set()
                terrain_files = [terrain.files[name] for name in sorted(used)] if used else []
                payload = {"ranked": rows, "counts": counts, "grid_points": len(points), "tracks": len(tracks),
                           "cells": list(cells), "terrain_files": terrain_files}
                write_json(checkpoint, {"run_hash": run_hash, "payload_hash": content_hash(payload), "payload": payload})
            done += 1
            points_searched += payload["grid_points"]
            ranked = merge_candidates(itertools.chain(ranked, payload["ranked"]), budget.top_k)
        except (DataUnavailable, ValueError, OSError) as error:
            failures.append({"tile": tile_id, "reason": str(error)})
    coarse = list(ranked)
    # Refine only global finalists; tile selection never controls refinement rank.
    refinement_failure = None
    refinement_points_searched, refinement_points_skipped = 0, 0
    if ranked and budget.refine_spacing_m < budget.spacing_m:
        chosen, seen = [], set()
        for row in ranked:
            approach = (tuple(row["flight_ids"]), tuple(round(t) for t in row["pass_emission_times_s"]))
            if approach not in seen:
                chosen.append(row)
                seen.add(approach)
            if len(chosen) >= budget.refine_finalists:
                break
        try:
            fine = budget.refine_spacing_m
            width = math.ceil(budget.spacing_m / fine)
            completed_rectangles = []
            for row in chosen:
                # Subdivide the refinement square as well, retaining hard grid limits.
                cx, cy = round(row["x"] / fine), round(row["y"] / fine)
                for y0 in range(cy - width, cy + width + 1, budget.tile_cells):
                    for x0 in range(cx - width, cx + width + 1, budget.tile_cells):
                        cells = (x0, y0, min(cx + width + 1, x0 + budget.tile_cells), min(cy + width + 1, y0 + budget.tile_cells))
                        points = tile_points(cells, fine, bounds, terrain, crs)
                        keep = np.ones(len(points), dtype=bool)
                        for left, bottom, right, top in completed_rectangles:
                            keep &= ~((points.x >= left * fine) & (points.x < right * fine)
                                      & (points.y >= bottom * fine) & (points.y < top * fine))
                        refinement_points_skipped += int((~keep).sum())
                        points = points[keep]
                        if not len(points):
                            continue
                        tracks = _tracks(indexes, _expanded_bounds(cells, fine, radius, crs), time_range_s, budget)
                        rows, _ = _score(points, tracks, events, measurements, budget, parameters, filters, start_window)
                        refinement_points_searched += len(points)
                        ranked = merge_candidates(itertools.chain(ranked, rows), budget.top_k)
                completed_rectangles.append((cx - width, cy - width, cx + width + 1, cy + width + 1))
        except (DataUnavailable, ValueError, OSError) as error:
            refinement_failure = str(error)
    coverage = [i.coverage_for(bounds, time_range_s) for i in indexes]
    # Aircraft outside the receiver rectangle can still be audible inside it.
    # Use a conservative geographic envelope for scope accounting as well as
    # expanded per-tile queries; cropped CONUS inputs have visible border gaps.
    angular = (1.6 * radius + 15000) / 110000
    lon_margin = angular / max(0.1, math.cos(math.radians(max(abs(bounds[1]), abs(bounds[3])))))
    flight_bounds = [max(-180, bounds[0] - lon_margin), max(-90, bounds[1] - angular),
                     min(180, bounds[2] + lon_margin), min(90, bounds[3] + angular)]
    # Sources partitioning time can jointly cover the request; union interval
    # coverage is checked only for all-type sources covering the whole spatial box.
    intervals = sorted(i.report["coverage"]["time_range_s"] for i in indexes if i.coverage_for(flight_bounds, i.report["coverage"]["time_range_s"])["scope_complete"])
    covered_until = time_range_s[0]
    for lo, hi in intervals:
        if lo <= covered_until:
            covered_until = max(covered_until, hi)
    data_complete = bool(covered_until >= time_range_s[1])
    complete = done == total and not failures and not refinement_failure and data_complete and not event_limit_applied
    report = {"run_hash": run_hash, "status": "complete" if complete else "partial", "ranked": ranked,
              "coarse_ranked": coarse, "tiles_total": total, "tiles_completed": done, "tiles_resumed": resumed,
              "tile_failures": failures, "unsearched_tiles": total - done, "grid_points_searched": points_searched,
              "data_coverage": coverage, "data_scope_complete": data_complete, "refinement_failure": refinement_failure,
              "refinement_points_searched": refinement_points_searched, "refinement_points_skipped": refinement_points_skipped,
              "required_flight_bounds": flight_bounds,
              "candidate_retention_limit": budget.top_k, "alternative_modes_exhaustively_assessed": False,
              "event_groups_proposed": len(events), "association_event_limit": event_limit,
              "all_event_groups_considered": not event_limit_applied,
              "event_limit_reason": "Configured event cap prevents assessing every independent group" if event_limit_applied else None,
              "elapsed_s": time.monotonic() - began, "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
              "bounded_concurrency": 1, "max_grid_points_per_tile": budget.tile_cells ** 2,
              "scoring_time_is_locked": True, "ground_truth_used_by_search": False, "scope": list(bounds)}
    write_json(output / "search-report.json", report)
    return report


def hashlib_array(value):
    import hashlib
    array = np.asarray(value)
    return hashlib.sha256(str(array.shape).encode() + str(array.dtype).encode() + array.tobytes()).hexdigest()
