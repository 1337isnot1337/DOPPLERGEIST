#!/usr/bin/env python3
"""Real NASA supplied-trajectory benchmark, outside the absolute UTC API.

Prepare, search and evaluate are separate commands. Search never reads microphone
truth. No calendar date, waveform or flight is generated, and no product acceptance
decision is made. Use the current dopplergeist package through explicit PYTHONPATH.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from pyproj import Transformer
from scipy import ndimage
from scipy.io import loadmat, wavfile
from dopplergeist.discovery import DiscoverySettings, _discover_baseline_events, discover_events
from dopplergeist.geometry import AcousticSupportError, Track, ecef, velocity_ecef
from dopplergeist.intake import intake_recording
from dopplergeist.matching import InsufficientRidgeSamples, RidgeTimes, UnreconciledHarmonicGroup, fit_ridge, prepare_events

SCOPE = "real_NASA_supplied_trajectory_session_clock"
SOURCE = "https://data.nasa.gov/docs/datasets/rfk401li/small_uav_acoustics.zip"
DESCRIPTION = "https://data.nasa.gov/docs/datasets/rfk401li/Data_Description_20160203.pdf"
REFERENCE_FRAMES = {
    "cub": dict(
        origin="mic1", lat=38.0953507, lon=-77.2633382, height=20.726,
        warning="Supplied GPS only; RTK unused. See publisher flight protocol and source quality fields."),
    "edge": dict(
        origin="mic3", lat=36.6797443, lon=-76.0376444, height=0.0,
        warning="Supplied GPS only; delivered coordinates may already be interpolated. Absolute microphone height and weather unmeasured."),
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def clean(x):
    if isinstance(x, dict): return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [clean(v) for v in x]
    if isinstance(x, np.ndarray): return clean(x.tolist())
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, np.bool_): return bool(x)
    if isinstance(x, (float, np.floating)): return float(x) if np.isfinite(x) else None
    return x


def write(path, x):
    Path(path).write_text(json.dumps(clean(x), indent=2, allow_nan=False) + "\n")


def read(path): return json.loads(Path(path).read_text())


def pinned_cases(path):
    selection = read(path)
    if selection.get("schema") != "nasa_measured_case_selection_v1":
        raise ValueError("Wrong pinned case selection schema")
    if not isinstance(selection.get("selection_rule"), str) or not selection["selection_rule"].strip():
        raise ValueError("Declare a selection rule before examining the recordings")
    if selection.get("selection_uses_audio_or_location_error") is not False:
        raise ValueError("This extension requires publisher-metadata-only selection")
    result = {}
    for item in selection["cases"]:
        name = item["case_id"]
        match = re.fullmatch(r"(cub|edge)_flyover_[0-9]{3}", name)
        digest, size = item["sha256"], item["size_bytes"]
        if not match or name in result or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid or duplicate pinned public case")
        if type(size) is not int or size <= 0:
            raise ValueError("Pinned source size must be a positive integer")
        result[name] = dict(REFERENCE_FRAMES[match.group(1)], sha256=digest, size_bytes=size,
            publisher_protocol=item.get("publisher_protocol"))
    if not result: raise ValueError("No pinned measured cases")
    return result, selection


def newdir(path):
    p = Path(path).resolve()
    p.mkdir(parents=True, exist_ok=False)
    return p


def enu(ned): return np.asarray(ned)[..., [1, 0, 2]] * [1, 1, -1]


def ordered(t):
    t = np.asarray(t)
    if t.ndim != 1 or len(t) < 3 or not np.all(np.isfinite(t)) or not np.all(np.diff(t) > 0):
        raise ValueError("Measured times must be finite, strictly ordered; no repair is performed")
    if t[0] < 0 or t[-1] >= 86400: raise ValueError("Only within-day publisher clocks are supported")
    return t


def timing(t, sr=None):
    d = np.diff(t)
    x = dict(count=len(t), first=t[0], last=t[-1], min_step_s=d.min(), median_step_s=np.median(d), max_step_s=d.max())
    if sr:
        error = t - t[0] - np.arange(len(t)) / sr
        x.update(nominal_rate_hz=sr, endpoint_effective_rate_hz=(len(t)-1)/(t[-1]-t[0]),
                 max_nominal_clock_deviation_s=np.max(np.abs(error)), end_nominal_clock_deviation_s=error[-1])
    return x


def prepare(args):
    selected, selection = pinned_cases(args.case_manifest)
    out = newdir(args.output)
    cases, domains, truth = [], {}, {}
    for name, published in selected.items():
        source = Path(args.source_directory)/(name + ".mat")
        if source.stat().st_size != published["size_bytes"] or sha(source) != published["sha256"]:
            raise ValueError("Not the pinned NASA source: " + str(source))
        original = loadmat(source, simplify_cells=True)
        a, v = original["acoustics"], original["vehicle_data"]
        if a["origin"] != published["origin"] or v["origin"] != published["origin"]:
            raise ValueError("Audio and GPS coordinate frames disagree")
        at, gt = ordered(a["utc_time"]), ordered(v["gps_utc_time"])
        pressure, gps = np.asarray(a["incident_pascals"]), np.asarray(v["gps_ned_meters"])
        if pressure.shape != (len(at), 4) or gps.shape != (len(gt), 3): raise ValueError("Unexpected source shape")
        if not np.all(np.isfinite(pressure)) or not np.all(np.isfinite(gps)): raise ValueError("Nonfinite real input")
        # Channel 2 is predeclared and differs from both survey-frame origins.
        arrays = dict(mono_pressure=pressure[:, 1], audio_seconds_of_day=at,
                      gps_seconds_of_day=gt, gps_ned_meters=gps)
        folder = out/name
        folder.mkdir()
        files = {}
        for key, data in arrays.items():
            path = folder/(key + ".npy")
            np.save(path, data, allow_pickle=False)
            files[key] = dict(path=str(path), sha256=sha(path), shape=data.shape, dtype=str(data.dtype))
        wavfile.write(folder/"mono_pressure_20000hz.wav", 20000, arrays["mono_pressure"])
        xyz = enu(gps)
        low = np.floor((xyz[:, :2].min(axis=0)-args.padding_m)/500)*500
        high = np.ceil((xyz[:, :2].max(axis=0)+args.padding_m)/500)*500
        domains[name] = dict(east_bounds_m=[low[0], high[0]], north_bounds_m=[low[1], high[1]],
            padding_m=args.padding_m, nominal_receiver_up_m=0,
            definition="Measured GPS footprint, fixed padding, rounded outward to500m survey-frame lattice.",
            target_positions_or_acoustic_fit_used=False,
            limitation="Conditional local domain from supplied flight, not national or blind-site search.")
        speed = np.linalg.norm(np.diff(xyz, axis=0), axis=1)/np.diff(gt)
        met = original.get("met_data")
        temp = np.asarray(met["temperature_celsius"]) if isinstance(met, dict) else np.array([])
        if temp.size and not np.all(np.isfinite(temp)): raise ValueError("Nonfinite measured weather")
        c = np.sqrt(1.4*287.05*(273.15+np.median(temp))) if temp.size else 343.0
        cases.append(dict(case_id=name, files=files, source_sha256=published["sha256"], source_url=SOURCE,
            source_size_bytes=published["size_bytes"], publisher_protocol=published["publisher_protocol"],
            mono_channel_one_based=2, reference={k: published[k] for k in ("lat", "lon", "height", "origin")},
            reference_role="Publisher coordinate origin distinct from target; rigid conversion only.",
            clock=dict(kind="publisher_UTC_seconds_of_day", calendar_date=None, unix_epoch=None,
                sample_zero_seconds_of_day=at[0], origin_shift="Subtract acoustic sample zero from both axes.",
                publisher_GPS_leap_seconds_already_applied=True, measured_absolute_clock_uncertainty=False),
            audio_timing=timing(at, 20000), gps_timing=timing(gt),
            gps_chord_speed_mps=dict(min=speed.min(), median=np.median(speed), max=speed.max()),
            waveform_resampled=False, all_original_GPS_rows_retained=True, source_warning=published["warning"],
            nominal_sound_speed_mps=c, measured_temperatures_celsius=temp,
            sound_speed_basis="Dry-air approximation from measured temperature; wind/humidity unmodeled." if temp.size else "Nominal343m/s; no weather measurement."))
        mic = np.asarray(a["mic_ned_meters"])
        if mic.shape != (4, 3) or not np.all(np.isfinite(mic)): raise ValueError("Invalid microphone table")
        truth[name] = dict(microphone_one_based=2, receiver_enu_m=enu(mic[1]), source_description=DESCRIPTION)
    write(out/"search-inputs.json", dict(scope=SCOPE, cases=cases, target_coordinates_in_objective=False,
        case_selection=selection, case_manifest_sha256=sha(args.case_manifest)))
    write(out/"search-domain.json", dict(scope=SCOPE, cases=domains))
    write(out/"evaluation-truth.json", dict(scope=SCOPE, cases=truth))
    write(out/"preparation.json", dict(scope=SCOPE, case_manifest_sha256=sha(args.case_manifest),
        search_inputs_sha256=sha(out/"search-inputs.json"), domain_sha256=sha(out/"search-domain.json"),
        truth_sha256=sha(out/"evaluation-truth.json"), synthetic_data_generated=False, localization_performed=False))
    print(json.dumps(dict(prepared=str(out), cases=list(selected))))


class OriginalMono:
    def __init__(self, mono, source_sha):
        self.mono = mono
        self.metadata = dict(sample_rate_hz=20000, duration_s=len(mono)/20000, source_sha256=source_sha)

    def iter_chunks(self, chunk_s=120, overlap_s=60):
        size, overlap = round(chunk_s*20000), round(overlap_s*20000)
        for first in range(0, len(self.mono), size-overlap):
            yield first/20000, self.mono[first:first+size]
            if first+size >= len(self.mono): break


def load_arrays(case):
    result = {}
    for key, item in case["files"].items():
        if sha(item["path"]) != item["sha256"]: raise ValueError("Measured data changed: " + key)
        result[key] = np.load(item["path"], mmap_mode="r", allow_pickle=False)
    return result


def make_track(case, arrays):
    ref = case["reference"]
    base = ecef(ref["lat"], ref["lon"], ref["height"])
    def to_xyz(point):
        point = np.asarray(point)
        return base + velocity_ecef(ref["lat"], ref["lon"], point[..., 0], point[..., 1], point[..., 2])
    xyz = to_xyz(enu(arrays["gps_ned_meters"]))
    transform = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)
    lon, lat, h = transform.transform(xyz[:, 0], xyz[:, 1], xyz[:, 2])
    t = arrays["gps_seconds_of_day"]-arrays["audio_seconds_of_day"][0]
    track = Track(case["case_id"], t, lat, lon, h, "NASA measured GPS")
    error = np.max(np.linalg.norm(xyz-track.xyz, axis=1))
    if error > 1e-4: raise ValueError("Coordinate round-trip error exceeds0.1mm")
    return track, to_xyz, error


def measurements(events, audio_time):
    settings, original = prepare_events(events)
    result = []
    for spec, freq, weight, extra in original:
        index = np.rint(spec.time*20000).astype(np.int64)
        if np.any(index < 0) or np.any(index >= len(audio_time)) or np.max(np.abs(index/20000-spec.time)) > 1e-8:
            raise ValueError("FFT centers do not map to exact original sample indices")
        result.append((RidgeTimes(audio_time[index]-audio_time[0]), freq, weight, extra))
    return settings, result


def fit_at(track, to_xyz, measurement, event, point, c, clock, drift):
    try:
        fit = fit_ridge(track, to_xyz(point), measurement, clock, event["f0_range_hz"], c,
                        event["quality"]["frequency_loss_scale_hz"], drift)
    except AcousticSupportError as error:
        return None, error.reason
    if not np.isfinite(fit.get("score", np.nan)) or fit.get("support_fraction") != 1.0:
        return None, "incomplete_acoustic_or_ridge_support"
    return fit, None


def modes(loss, east, north, separation):
    finite = np.isfinite(loss)
    values = np.where(finite, loss, np.inf)
    local = finite & (values == ndimage.minimum_filter(values, size=3, mode="constant", cval=np.inf))
    points = sorted(np.argwhere(local), key=lambda ij: values[tuple(ij)])
    result = []
    for iy, ix in points:
        if any(np.hypot(east[ix]-m["east_m"], north[iy]-m["north_m"]) < separation for m in result): continue
        result.append(dict(east_m=east[ix], north_m=north[iy], loss_hz=values[iy, ix],
                           domain_edge=ix in (0, len(east)-1) or iy in (0, len(north)-1)))
        if len(result) >= 8: break
    return result


def search(args):
    source, domains = read(args.inputs), read(args.domain)
    if source.get("scope") != SCOPE or domains.get("scope") != SCOPE: raise ValueError("Wrong input scope")
    if not np.isfinite(args.grid_step_m) or args.grid_step_m <= 0: raise ValueError("Invalid grid step")
    if not all(0 <= d <= 0.1 for d in args.drift_fractions): raise ValueError("Invalid drift domain")
    settings = DiscoverySettings(window_s=args.discovery_window_s, hop_s=args.discovery_hop_s)
    if args.discovery_mode == "production" and settings != DiscoverySettings():
        raise ValueError("Production discovery requires default settings; use --discovery-mode legacy for historical controls")
    out = newdir(args.output)
    manifest = dict(scope=SCOPE, case_manifest_sha256=source.get("case_manifest_sha256"),
        case_selection=source.get("case_selection"),
        inputs_sha256=sha(args.inputs), domain_sha256=sha(args.domain), grid_step_m=args.grid_step_m,
        clock_offsets_s=args.clock_offsets_s, drift_fractions=args.drift_fractions, receiver_up_m=args.receiver_up_m,
        grid_nodes="Cell centers, with no target coordinate inserted", discovery_settings=asdict(settings),
        discovery_mode=args.discovery_mode,
        target_truth_loaded=False, synthetic_data_generated=False, absolute_UTC_validated=False,
        historical_traffic_acquisition_validated=False, product_acceptance=None, calendar_date=None, cases=[])
    write(out/"run-manifest.json", manifest)
    for case in source["cases"]:
        name = case["case_id"]
        folder = out/name
        folder.mkdir()
        arrays = load_arrays(case)
        # This phase gets no GPS or microphone position inputs.
        if args.discovery_mode == "production":
            # Export the pinned, single-microphone pressure samples without
            # normalization; do not mix microphones at distinct positions.
            audio = folder/"mono_pressure_20000hz.wav"
            wavfile.write(audio, 20000, arrays["mono_pressure"])
            recording = intake_recording(audio, folder/"intake", sample_rate_hz=4000)
            events = discover_events(recording, output_dir=folder/"discovery", plot_summary=False)
        else:
            events = _discover_baseline_events(
                OriginalMono(arrays["mono_pressure"], case["source_sha256"]), settings=settings)
        write(folder/"audio-only-discovery.json", dict(events=events, settings=asdict(settings),
            discovery_mode=args.discovery_mode,
            selection="Every returned audio proposal retained; no location-based selection",
            supplied_trajectory_count=1, encounter_count=None, encounter_count_assumed=False))
        summary = dict(case_id=name, supplied_trajectory_count=1, encounter_count=None, encounter_count_assumed=False,
            acoustic_proposals=len(events), source_warning=case["source_warning"],
            audio_timing=case["audio_timing"], gps_timing=case["gps_timing"], results=[])
        try:
            event_settings, measured = measurements(events, arrays["audio_seconds_of_day"])
        except (UnreconciledHarmonicGroup, InsufficientRidgeSamples) as error:
            status = "insufficient_ridge_samples" if isinstance(error, InsufficientRidgeSamples) else "unreconciled_discovery_group"
            summary.update(status=status, message=str(error))
            write(folder/"case-results.json", summary)
            manifest["cases"].append(summary)
            write(out/"run-manifest.json", manifest)
            continue
        summary["matching_proposals"] = len(event_settings)
        track, to_xyz, transform_error = make_track(case, arrays)
        c = case["nominal_sound_speed_mps"] if args.sound_speed_mps is None else args.sound_speed_mps
        if not np.isfinite(c) or c <= 0: raise ValueError("Invalid sound speed")
        motion = dict(globally_subsonic=True)
        try:
            track.validate_motion_support(c)
        except AcousticSupportError as error:
            motion = dict(globally_subsonic=False, reason=error.reason,
                          unsupported_emission_intervals_s=error.emission_intervals_s)
        domain = domains["cases"][name]
        def centers(bounds): return np.arange(bounds[0]+args.grid_step_m/2, bounds[1], args.grid_step_m)
        east, north = centers(domain["east_bounds_m"]), centers(domain["north_bounds_m"])
        if not len(east) or not len(north) or len(east)*len(north) > args.max_grid_points:
            raise ValueError("Grid exceeds explicit budget or is empty; no truncated search")
        summary.update(track_support=motion,
            transform_roundtrip_max_m=transform_error, sound_speed_mps=c,
            sound_speed_basis=case["sound_speed_basis"] if args.sound_speed_mps is None else "Explicit sensitivity override")
        for i, (event, measured_ridge) in enumerate(zip(event_settings, measured)):
            np.savez_compressed(folder/f"ridge-{i:03d}.npz", time_s=measured_ridge[0].time,
                                frequency_hz=measured_ridge[1], weight=measured_ridge[2])
            write(folder/f"event-{i:03d}.json", event)
            for clock in args.clock_offsets_s:
                for drift in args.drift_fractions:
                    for up in args.receiver_up_m:
                        identity = f"ridge-{i:03d}-clock-{clock:g}-drift-{drift:g}-up-{up:g}"
                        loss = np.full((len(north), len(east)), np.nan)
                        reasons = Counter()
                        for iy, y in enumerate(north):
                            for ix, x in enumerate(east):
                                fit, reason = fit_at(track, to_xyz, measured_ridge, event, [x, y, up], c, clock, drift)
                                if reason: reasons[reason] += 1
                                else: loss[iy, ix] = -fit["score"]
                        found = modes(loss, east, north, max(100, 2*args.grid_step_m))
                        for mode in found:
                            mode["fit"], _ = fit_at(track, to_xyz, measured_ridge, event,
                                [mode["east_m"], mode["north_m"], up], c, clock, drift)
                        grid_path = folder/(identity + ".npz")
                        np.savez_compressed(grid_path, east_m=east, north_m=north, loss_hz=loss, evaluated=np.isfinite(loss))
                        item = dict(id=identity, event_index=i, event_id=event["event_id"], clock_offset_s=clock,
                            drift_fraction=drift, receiver_up_m=up, grid_points=loss.size,
                            evaluated_grid_points=np.isfinite(loss).sum(), unknown_grid_points=(~np.isfinite(loss)).sum(),
                            unknown_reasons=reasons, grid_assessment_complete=not reasons, local_modes=found,
                            diagnostic_loss_scale_hz=event["quality"]["frequency_loss_scale_hz"],
                            conditional_scenario=True, unique_location_established=False,
                            status="supported_grid_minima_only" if found else "no_supported_fit")
                        if found:
                            mask = np.isfinite(loss) & (loss <= found[0]["loss_hz"]+item["diagnostic_loss_scale_hz"])
                            yy, xx = np.where(mask)
                            item["within_one_loss_scale"] = dict(count=len(xx),
                                east_bounds_m=[east[xx].min(), east[xx].max()], north_bounds_m=[north[yy].min(), north[yy].max()],
                                max_distance_from_best_m=np.max(np.hypot(east[xx]-found[0]["east_m"], north[yy]-found[0]["north_m"])),
                                interpretation="Descriptive contour, not a probability or confidence interval")
                        write(folder/(identity + ".json"), item)
                        summary["results"].append(item)
                        write(folder/"case-results.json", summary)
                        print(json.dumps(clean(dict(case=name, result=identity, evaluated=item["evaluated_grid_points"],
                            unknown=item["unknown_grid_points"], best=found[0] if found else None))), flush=True)
        if not events: summary["status"] = "no_proposal_from_configured_discovery"
        write(folder/"case-results.json", summary)
        manifest["cases"].append(summary)
        write(out/"run-manifest.json", manifest)
    write(out/"frozen-search.json", dict(scope=SCOPE, target_truth_loaded=False,
                                       run_manifest_sha256=sha(out/"run-manifest.json"), product_acceptance=None))


def evaluate(args):
    folder = Path(args.search_directory)
    frozen = read(folder/"frozen-search.json")
    if sha(folder/"run-manifest.json") != frozen["run_manifest_sha256"]: raise ValueError("Search changed after freezing")
    manifest, truth = read(folder/"run-manifest.json"), read(args.truth)
    if truth.get("scope") != SCOPE or manifest["target_truth_loaded"] is not False: raise ValueError("Invalid truth separation")
    if Path(args.output).exists(): raise FileExistsError("Evaluation output exists")
    rows = []
    for case in manifest["cases"]:
        target = np.asarray(truth["cases"][case["case_id"]]["receiver_enu_m"])
        for result in case["results"]:
            for rank, mode in enumerate(result["local_modes"], 1):
                point = np.array([mode["east_m"], mode["north_m"], result["receiver_up_m"]])
                rows.append(dict(case_id=case["case_id"], result_id=result["id"], mode_rank=rank,
                    horizontal_error_m=np.linalg.norm(point[:2]-target[:2]), position_error_m=np.linalg.norm(point-target),
                    loss_hz=mode["loss_hz"], grid_support_complete=result["grid_assessment_complete"]))
    write(args.output, dict(scope=SCOPE, frozen_search_sha256=sha(folder/"frozen-search.json"),
        truth_sha256=sha(args.truth), rows=rows, product_acceptance=None, generalization_established=False,
        interpretation="Measured errors for frozen conditional modes; no unique national localization or calibrated accuracy claim."))
    print(json.dumps(dict(evaluation=args.output, mode_rows=len(rows))))


def numbers(text):
    values = [float(x) for x in text.split(",")]
    if not values or not np.all(np.isfinite(values)) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("Need distinct finite comma-separated numbers")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--source-directory", required=True)
    p.add_argument("--case-manifest", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--padding-m", type=float, default=1000.0)
    p.set_defaults(func=prepare)
    p = commands.add_parser("search")
    p.add_argument("--inputs", required=True)
    p.add_argument("--domain", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--discovery-mode", choices=("production", "legacy"), default="production",
                   help="Current intake/discovery, or the historical baseline detector used in the 2026-11-03 report")
    p.add_argument("--discovery-window-s", type=float, default=2.0)
    p.add_argument("--discovery-hop-s", type=float, default=0.5)
    p.add_argument("--grid-step-m", type=float, default=50.0)
    p.add_argument("--max-grid-points", type=int, default=25000)
    p.add_argument("--clock-offsets-s", type=numbers, default=[0.0])
    p.add_argument("--drift-fractions", type=numbers, default=[0.0, 0.02])
    p.add_argument("--receiver-up-m", type=numbers, default=[0.0])
    p.add_argument("--sound-speed-mps", type=float)
    p.set_defaults(func=search)
    p = commands.add_parser("evaluate")
    p.add_argument("--search-directory", required=True)
    p.add_argument("--truth", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=evaluate)
    args = parser.parse_args()
    if hasattr(args, "padding_m") and (not np.isfinite(args.padding_m) or args.padding_m <= 0):
        parser.error("Padding must be finite and positive")
    args.func(args)


if __name__ == "__main__":
    main()
