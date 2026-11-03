"""Numerically inspect frozen six-event trajectories and emission-time residuals."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    started = time.monotonic()
    archive_audit = json.loads((root / "archive-audit.json").read_bytes())
    for entry in archive_audit["wheel"]["files"]:
        path = root / "frozen-runtime" / entry["path"].removeprefix("src/")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    sys.path.insert(0, str(root / "frozen-runtime"))
    import numpy as np
    from aircraft_geoloc.data_access import FlightIndex
    from aircraft_geoloc.geometry import ecef
    from aircraft_geoloc.matching import prepare_events

    index = FlightIndex(root / "restored/derived-inputs/flights-runtime-v2.sqlite")
    coverage = index.report["coverage"]
    tracks = list(index.query(coverage["bounds"], coverage["time_range_s"]))
    assert len(tracks) == archive_audit["index"]["segment_payloads_verified"]
    c = 343.0
    track_reports = []
    for track in tracks:
        extrema = []
        root_count = 0
        for i, dt in enumerate(np.diff(track.time)):
            # Hermite position is cubic. Velocity is quadratic in normalized u.
            a = 3 * track.spline.c[0, i] * dt ** 2
            b = 2 * track.spline.c[1, i] * dt
            d = track.spline.c[2, i]
            speed_squared = np.array([np.dot(d, d), 2 * np.dot(b, d),
                                      np.dot(b, b) + 2 * np.dot(a, d),
                                      2 * np.dot(a, b), np.dot(a, a)])
            derivative = speed_squared[1:] * np.arange(1, 5)
            roots = np.polynomial.polynomial.polyroots(derivative)
            candidates = [0.0, 1.0]
            for value in roots:
                if abs(value.imag) <= 1e-8 * max(1.0, abs(value.real)) and 0 <= value.real <= 1:
                    candidates.append(float(value.real))
                    root_count += 1
            speeds = [float(np.linalg.norm(a * u * u + b * u + d)) for u in candidates]
            k = int(np.argmax(speeds))
            # A separate dense sample catches polynomial/root-evaluation mistakes.
            sampled = max(float(np.linalg.norm(a * u * u + b * u + d)) for u in np.linspace(0, 1, 33))
            assert sampled <= speeds[k] + 1e-7
            extrema.append({"speed_m_s": speeds[k], "interval_index": i,
                            "interval_s": [float(track.time[i]), float(track.time[i + 1])],
                            "fraction": candidates[k]})
        maximum = max(extrema, key=lambda item: item["speed_m_s"])
        track_reports.append({"track_id": track.id, "intervals": len(extrema),
                              "stationary_roots_considered": root_count, "maximum": maximum,
                              "numerically_subsonic_at_c_343": maximum["speed_m_s"] < c,
                              "minimum_observer_independent_arrival_derivative_bound": 1 - maximum["speed_m_s"] / c})
    evidence = root / "restored/verification"
    search = json.loads((evidence / "terminal-search-search-report.json").read_bytes())
    discovery = json.loads((evidence / "terminal-discovery-discovery.json").read_bytes())
    events, measurements = prepare_events(discovery["events"])
    leading = search["ranked"][0]
    observer = ecef(leading["lat"], leading["lon"], leading["elev_m"])
    by_id = {track.id: track for track in tracks}
    event_reports = []
    for event_index, track_id in zip(leading["event_indices"], leading["flight_ids"]):
        ridge_times = measurements[event_index][0].time
        receive = leading["recording_start_time_s"] + np.asarray(ridge_times)
        factor, emission, distance = by_id[track_id].acoustic(receive, observer, c=c)
        finite = np.isfinite(np.column_stack((factor, emission, distance))).all(axis=1)
        residual = (emission[finite] - receive[finite]) + distance[finite] / c
        max_residual = float(np.max(np.abs(residual))) if len(residual) else None
        ulp = float(np.max(np.spacing(receive)))
        event_reports.append({"event_index": event_index, "track_id": track_id,
                              "ridge_samples": len(receive), "finite_samples": int(finite.sum()),
                              "maximum_receive_time_equation_residual_s": max_residual,
                              "maximum_receive_time_equation_residual_m": None if max_residual is None else c * max_residual,
                              "absolute_epoch_float_spacing_s": ulp,
                              "all_samples_within_five_epoch_ulps": bool(finite.all() and max_residual <= 5 * ulp),
                              "all_factors_positive": bool(finite.all() and np.all(factor > 0))})
    out = {"scope": "Post-run numerical necessary-condition checks on the restored finite synthetic inputs and fixed leading search state. No production fix, formal interval certificate, real-source validation or decision change.",
           "checked_at_utc": datetime.now(timezone.utc).isoformat(),
           "runtime_commit": archive_audit["runtime_commit"],
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "method": "All native Hermite interval endpoints and real stationary roots of squared speed, with 33-point sample cross-check per interval; direct emission-time equation residual at every selected ridge sample.",
           "sound_speed_m_s": c, "tracks": track_reports, "event_residuals": event_reports,
           "all_tracks_numerically_subsonic": all(item["numerically_subsonic_at_c_343"] for item in track_reports),
           "all_selected_emission_residuals_small": all(item["all_samples_within_five_epoch_ulps"] for item in event_reports),
           "elapsed_s": time.monotonic() - started}
    (root / "motion-conditions-audit.json").write_text(json.dumps(out, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"tracks": len(tracks), "intervals": sum(item["intervals"] for item in track_reports),
                      "maximum_speed_m_s": max(item["maximum"]["speed_m_s"] for item in track_reports),
                      "all_tracks_numerically_subsonic": out["all_tracks_numerically_subsonic"],
                      "all_selected_emission_residuals_small": out["all_selected_emission_residuals_small"],
                      "elapsed_s": out["elapsed_s"]}))


if __name__ == "__main__":
    main()
