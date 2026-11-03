"""Automatic stage orchestration; scientific producers own their algorithms."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

from .contracts import utc_timestamp, validate_candidate, validate_event, validate_request
from .jobs import write_json


def _digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def analyze(request, output_dir, config=None, progress=lambda *args, **kwargs: None):
    request = validate_request(request)
    config = config or {}
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "provenance.json").exists():
        raise FileExistsError("Analysis output exists; use a new directory")
    began = time.monotonic()
    sources = {p.name: _digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    provenance = {"request": request, "operator_configuration_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                  "source_sha256": _digest(request["audio_path"]), "implementation_files": sources,
                  "ground_truth_used_by_search": False, "event_selection": "automatic_whole_recording"}
    write_json(output / "request.json", request)
    write_json(output / "provenance.json", provenance)
    state = {"coverage": {"search_complete": False, "data_status": "unavailable", "limitations": [], "requested_area": request["search"]}}

    def finish(status, reason_code=None, message=None, **fields):
        provenance["elapsed_s"] = time.monotonic() - began
        provenance["status"] = status
        provenance["coverage"] = fields.get("coverage", state["coverage"])
        write_json(output / "provenance.json", provenance)
        artifacts = {"provenance": "provenance.json", "request": "request.json"}
        for name, path in (("intake", "intake/intake.json"), ("recording", "intake/recording.json"),
                           ("discovery", "discovery/discovery.json"), ("discovery_plot", "discovery/discovery.png"),
                           ("search_report", "search/search-report.json"), ("refinement", "refined-candidates.json"), ("data_provenance", "data-provenance.json"), ("decision", "decision.json")):
            if (output / path).is_file():
                artifacts[name] = path
        for path in sorted((output / "discovery").glob("event-*.png")):
            artifacts[path.stem] = path.relative_to(output).as_posix()
        value = dict(state, status=status, stage="complete", progress=1, artifacts=artifacts, **fields)
        if reason_code:
            value.update(reason_code=reason_code, message=message)
        return value

    try:
        from .intake import AudioIntakeError, intake_recording
        from .discovery import discover_events
    except ImportError as exc:
        return finish("failed", "component_unavailable", f"Automatic audio components are not installed: {exc}")
    progress("intake", 0.05)
    try:
        recording = intake_recording(request["audio_path"], output / "intake", time_window=request.get("time_window"))
    except AudioIntakeError as exc:
        return finish("failed", exc.code, str(exc))
    state["recording"] = recording.metadata
    progress("discovery", 0.15, recording=recording.metadata)
    events = [validate_event(event) for event in discover_events(recording, output_dir=output / "discovery")]
    state["events"] = events
    provenance["discovered_events"] = len(events)
    if recording.time_status == "needs_input":
        return finish("needs_input", "recording_time_required", "Supply a defensible UTC window for the start of this recording. File creation and upload times are not recording clocks.", required_fields=["time_window"])
    if not events:
        return finish("inconclusive", "no_supported_events", "No supported moving-tone Doppler events were discovered in the recording.")
    progress("acquisition", 0.35, **state)
    try:
        from .data_access import DataUnavailable
        search, prepared_events, measurements, indexes, terrain = _search(request, recording, events, output, config, lambda: progress("search", 0.55, **state))
    except ImportError as exc:
        return finish("failed", "component_unavailable", f"Automatic matching/data components are not installed: {exc}")
    except MissingData as exc:
        state["coverage"]["limitations"].append(str(exc))
        return finish("inconclusive", "data_unavailable", str(exc))
    except DataUnavailable as exc:
        state["coverage"]["limitations"].append(str(exc))
        return finish("failed", "data_unavailable", str(exc))
    state["coverage"] = _coverage(request, search, config)
    provenance["search_run_hash"] = search.get("run_hash")
    progress("refinement", 0.85, **state)
    return _decide(search, events, prepared_events, measurements, indexes, terrain, state, output, config, finish, lambda: progress("decision", 0.95, **state))


class MissingData(ValueError):
    pass


def _search(request, recording, events, output, config, search_progress):
    from .data_access import CONUS, FlightIndex, acquire_inputs
    from .matching import prepare_events
    from .terrain import Terrain
    from .tiled_search import SearchBudget, search_national
    c = float(config.get("sound_speed_mps", 343.0))
    max_distance = float(config.get("max_distance_m", 20000.0))
    prepared, measurements = prepare_events(events, c=c, max_distance_m=max_distance)
    window = recording.metadata["time_window"]
    lo, hi = (utc_timestamp(window[name]).timestamp() for name in ("start_utc", "end_utc"))
    if not config.get("flight_indexes") and not config.get("cache_root"):
        raise MissingData("Historical flight/terrain data are not configured. The operator must provide cache_root or prebuilt flight indexes with a terrain model.")
    first_day = datetime.fromtimestamp(lo-max_distance/300-30, timezone.utc).date()
    last_day = datetime.fromtimestamp(hi+recording.metadata["duration_s"]+30, timezone.utc).date()
    acquisition_days = (last_day-first_day).days+1
    if not config.get("flight_indexes") and acquisition_days > config.get("max_acquisition_days", 3):
        raise MissingData("Recording time window exceeds the configured historical-data acquisition budget. Supply a narrower defensible window.")
    ground = config.get("terrain", {})
    hashes = {"terrain_configuration": ground}
    if ground.get("rasters") or "constant_m" in ground:
        # Explicit offline/test terrain override; normal provider acquisition stays
        # in the data owner's adapter. Never infer flight coverage from this model.
        if not config.get("flight_indexes"):
            raise MissingData("A declared local terrain model requires prebuilt flight indexes.")
        indexes = [FlightIndex(path) for path in config["flight_indexes"]]
        terrain = Terrain(ground.get("rasters", []), ground.get("constant_m"), ground.get("geoid_raster"))
        time_range = (lo-max_distance/300-30, hi+recording.metadata["duration_s"]+30)
        bounds = request["search"].get("bounds_wsen", CONUS)
        hashes["terrain_rasters"] = {str(path): _digest(path) for path in ground.get("rasters", [])}
    else:
        bundle = acquire_inputs(request, recording.metadata, cache_root=config.get("cache_root", output / "cache"),
                                index_paths=config.get("flight_indexes"), offline=config.get("offline", True),
                                terrain_options=ground, max_sound_range_m=max_distance)
        indexes, terrain, time_range, bounds = bundle.indexes, bundle.terrain, bundle.time_range_s, bundle.bounds
    if ground.get("geoid_raster"):
        hashes["geoid_sha256"] = _digest(ground["geoid_raster"])
    search_progress()
    # A supplied interval is never collapsed to its midpoint. Every event/tile
    # uses the same recording-start clock and globally comparable score units.
    scoring = {"mode": "robust_ridge", "c": c, "time_origin": lo if lo == hi else None,
               "time_sweep_s": 0 if lo == hi else 5, "time_step_s": 0.5,
               "recording_start_window_s": [lo, hi]}
    filters = {"association": "subsets", **config.get("filters", {})}
    filters.setdefault("max_events", len(prepared))
    report = search_national(indexes, terrain, prepared, measurements, time_range_s=time_range, output_dir=output / "search",
                             bounds=bounds, budget=SearchBudget(**config.get("search_budget", {})),
                             scoring=scoring, filters=filters, input_hashes=hashes)
    write_json(output / "data-provenance.json", {"flight_indexes": [index.report for index in indexes],
               "terrain": terrain.provenance() if hasattr(terrain, "provenance") else hashes})
    return report, prepared, measurements, indexes, terrain


def _coverage(request, search, config):
    limitations = ["Historical receiver archives may omit aircraft or trajectory samples."]
    search_complete = (search.get("tiles_total", 0) > 0 and search.get("tiles_completed") == search.get("tiles_total")
                       and not search.get("tile_failures") and not search.get("refinement_failure"))
    if not search_complete:
        limitations.append("Search did not complete the full requested tile work or refinement.")
    if "constant_m" in config.get("terrain", {}):
        limitations.append("A constant terrain model was supplied; real terrain and altitude-datum accuracy are not established.")
    if search.get("alternative_modes_exhaustively_assessed") is not True:
        limitations.append("Candidate retention is bounded; exhaustive alternative-location assessment is not established.")
    missing = [str(item) for item in search.get("tile_failures", [])]
    if not search.get("data_scope_complete"):
        missing.append("historical_flight_scope_or_audible_border_region")
        limitations.append("Flight inputs do not establish complete coverage of the required emission-time interval and audible border region.")
    return {"search_complete": search_complete, "data_status": "available" if search.get("data_scope_complete") else "partial",
            "limitations": limitations, "requested_area": request["search"], "missing_data": missing}


def _comparable_refinement(candidate, original, prepared_events):
    """Preserve newer normalized results; adapt only older raw-loss producers."""
    if (original.get("score_kind") == "matched_group_support_minus_normalized_residual"
            and candidate.get("score_kind") != "matched_group_support_minus_normalized_residual"):
        from .matching import association_score
        chosen = [prepared_events[i] for i in original["event_indices"]]
        candidate = association_score(candidate, chosen)
    if not math.isfinite(candidate["score"]):
        raise ValueError("Refinement no longer supports the matched event association")
    return candidate


def _decide(search, events, prepared_events, measurements, indexes, terrain, state, output, config, finish, decision_progress):
    # The confidence producer supplies this adapter; missing decision machinery
    # can never turn the highest raw score into a supported location.
    from .confidence import decide_location
    from .matching import profile_candidate, refine_candidate
    raw = list(search.get("ranked", []))
    refined, refinement_failures = [], []
    window = state["recording"]["time_window"]
    start_window = tuple(utc_timestamp(window[key]).timestamp() for key in ("start_utc", "end_utc"))
    # Refine global competing approaches with their original whole trajectories.
    # The index iterator is bounded by the same local acoustic support envelope.
    def approach(row):
        return (tuple(row.get("event_indices", range(len(prepared_events)))), tuple(row["flight_ids"]),
                tuple(round(t) for t in row.get("pass_emission_times_s", [])))


    seen, track_sets = set(), {}
    best_refined_score = -math.inf
    for row in raw:
        key = approach(row)
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > config.get("refine_finalists", 5):
            break
        try:
            max_range = float(config.get("max_distance_m", 20000.0))
            margin = max_range / 60000.0 + 0.3
            bounds = (row["lon"]-margin, row["lat"]-margin, row["lon"]+margin, row["lat"]+margin)
            needed = set(row["flight_ids"])
            tracks = {}
            lo = start_window[0] + min(e["start_s"] for e in prepared_events) - max_range / 300 - 120
            hi = start_window[1] + max(e["end_s"] for e in prepared_events) + 120
            for index in indexes:
                for track in index.query(bounds, (lo, hi)):
                    if track.id in needed:
                        tracks[track.id] = track
                        sample_limit = config.get("search_budget", {}).get("max_track_samples_per_tile", 500000)
                        if sum(len(item.time) for item in tracks.values()) > sample_limit:
                            raise ValueError("Refinement trajectory sample budget exceeded")
            if needed - tracks.keys():
                raise ValueError("Candidate flight segments are unavailable for refinement")
            row = dict(row, altitude_basis={flight: sorted(set(getattr(track, "altitude_basis", ["unspecified"]))) for flight, track in tracks.items()})
            candidate = refine_candidate(row, tracks, prepared_events, measurements, terrain,
                                         radius_m=config.get("refine_radius_m", 500.0),
                                         recording_start_window_s=start_window, c=config.get("sound_speed_mps", 343.0))
            candidate = _comparable_refinement(candidate, row, prepared_events)
            refined.append(candidate)
            if candidate["score"] > best_refined_score:
                best_refined_score = candidate["score"]
                track_sets = {key: tracks}
        except (ValueError, KeyError) as exc:
            refinement_failures.append(str(exc))
    raw.extend(refined)
    order = lambda row: (row["score"], bool(row.get("sensitivity", {}).get("complete")), len(row.get("sensitivity", {}).get("sources", [])))
    raw.sort(key=order, reverse=True)
    if raw and approach(raw[0]) in track_sets:
        leading = raw[0]
        try:
            profiled = profile_candidate(leading, track_sets[approach(leading)], prepared_events, measurements, terrain,
                         radius_m=config.get("refine_radius_m", 500.0), recording_start_window_s=start_window,
                         c=config.get("sound_speed_mps", 343.0))
            # Full profiling updates this exact hypothesis. Its earlier, limited
            # envelope must not compete with incomplete evidence or score roundoff.
            raw[0] = _comparable_refinement(profiled, leading, prepared_events)
        except (ValueError, KeyError) as exc:
            refinement_failures.append(f"Sensitivity profiling: {exc}")
            raw[0] = dict(leading, sensitivity={"complete": False, "sources": [],
                         "failures": [{"source": "profiling", "reason": str(exc)}]})
        # Preserve other modes; a different leader must satisfy its own full
        # sensitivity gate, without borrowing this hypothesis's profile.
        raw.sort(key=order, reverse=True)
    candidates, rows = [], []
    for row in raw:
        event_ids, flight_ids = [], []
        selected_events = [prepared_events[i] for i in row.get("event_indices", range(len(prepared_events)))]
        for event, flight in zip(selected_events, row["flight_ids"]):
            ids = event.get("event_ids", [event["event_id"]])
            event_ids.extend(ids)
            flight_ids.extend([flight]*len(ids))
        candidate = {"lat": float(row["lat"]), "lon": float(row["lon"]), "score": float(row["score"]),
                     "score_kind": row.get("score_kind", "negative_robust_ridge_loss_hz"), "event_ids": event_ids,
                     "flight_ids": flight_ids, "recording_start_utc": datetime.fromtimestamp(row["recording_start_time_s"], timezone.utc).isoformat().replace("+00:00", "Z")}
        sensitivity = row.get("sensitivity")
        if sensitivity and sensitivity.get("complete") and not sensitivity.get("boundary_limited"):
            candidate["uncertainty"] = {key: sensitivity[key] for key in ("radius_m", "method", "kind")}
        candidates.append(validate_candidate(candidate))
        rows.append(row)
    best = rows[0] if rows else {}
    original_ids = {event["event_id"]: event.get("event_ids", [event["event_id"]]) for event in prepared_events}
    unmatched_groups = best.get("unmatched_event_ids", list(original_ids) if not rows else [])
    unmatched_ids = [event_id for group in unmatched_groups for event_id in original_ids.get(group, [group])]
    diagnostics = {"recording_start_window_s": list(start_window), "unmatched_event_ids": unmatched_ids, "clock_locked": search.get("scoring_time_is_locked", False), "refinement_failures": refinement_failures,
                   "refinement_boundary_limited": best.get("sensitivity", {}).get("boundary_limited", True),
                   "sensitivity": best.get("sensitivity", {}),
                   "altitude_basis": best.get("altitude_basis", {}),
                   "alternatives_evaluated": search.get("alternative_modes_exhaustively_assessed") is True and search.get("status") == "complete" and not refinement_failures and len(seen) <= config.get("refine_finalists", 5)}
    matched_events = [prepared_events[i] for i in best.get("event_indices", range(len(prepared_events)))]
    for event, evidence in zip(matched_events, best.get("event_diagnostics", [])):
        for event_id in event.get("event_ids", [event["event_id"]]):
            diagnostics[event_id] = evidence
    write_json(output / "refined-candidates.json", {"ranked": rows, "matching_diagnostics": diagnostics})
    decision_progress()
    decision = decide_location(events, candidates, state["coverage"], matching_diagnostics=diagnostics)
    decision["candidates"] = candidates

    write_json(output / "decision.json", decision)
    fields = {key: value for key, value in decision.items() if key not in {"schema_version", "job_id", "status", "stage", "progress", "artifacts", "recording", "events", "diagnostics"}}
    status = decision["status"]
    reason = fields.pop("reason_code", None)
    message = fields.pop("message", None)
    return finish(status, reason, message, **fields)
