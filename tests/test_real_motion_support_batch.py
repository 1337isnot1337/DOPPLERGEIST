"""Motion-support checks on the archived four-aircraft observation audit."""
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from dopplergeist import geometry


def observed_tracks(relative=False):
    path = Path(__file__).resolve().parents[1] / "research/trajectory-motion/frozen/canonical-observations.json"
    grouped = defaultdict(list)
    for row in json.loads(path.read_text()):
        grouped[row["flight_id"]].append(row)
    tracks = []
    for identity, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row["time_s"])
        values = {name: np.array([row[name] for row in rows]) for name in
                  ("time_s", "lat", "lon", "alt_m", "east_mps", "north_mps", "up_mps")}
        if relative:
            # The same observed trajectory expressed on a recording-relative clock.
            values["time_s"] -= values["time_s"][0]
        velocity = geometry.velocity_ecef(values["lat"], values["lon"],
            values["east_mps"], values["north_mps"], values["up_mps"])
        tracks.append(geometry.Track(identity, values["time_s"], values["lat"], values["lon"],
                                     values["alt_m"], rows[0]["typecode"], velocity))
    return tracks


def original_indices(track, c):
    """Original scalar traversal, including its lazy extrema cache."""
    limit = c*(1-1e-10)
    suspicious = np.flatnonzero(track._speed_upper >= limit)
    for i in suspicious:
        dt = track.time[i+1]-track.time[i]
        if np.isnan(track._speed_peak[i]):
            a, b, d = track.derivative.c[:, i]
            a, b = a*dt**2, b*dt
            stationary = [2*np.dot(b, d), 2*(np.dot(b, b)+2*np.dot(a, d)),
                          6*np.dot(a, b), 4*np.dot(a, a)]
            roots = np.polynomial.polynomial.polyroots(stationary)
            samples = [0., 1.] + [float(r.real) for r in roots
                if abs(r.imag) <= 1e-8 and 0 < r.real < 1]
            track._speed_peak[i] = max(np.linalg.norm((a*u+b)*u+d) for u in samples)
    return suspicious[track._speed_peak[suspicious] >= limit]


def original_envelopes(track, observer, c):
    """Original one-interval arithmetic is the endpoint regression oracle."""
    envelopes = []
    for i in original_indices(track, c):
        dt = track.time[i+1]-track.time[i]
        p0, p1 = track.xyz[i:i+2]
        v0, v1 = track.speed_vector(track.time[i:i+2])
        controls = np.array([p0, p0+dt*v0/3, p1-dt*v1/3, p1])
        lo, hi = controls.min(axis=0), controls.max(axis=0)
        nearest = np.maximum(np.maximum(lo-observer, observer-hi), 0)
        farthest = np.maximum(np.abs(lo-observer), np.abs(hi-observer))
        arrival_lo = track.time[i]+np.linalg.norm(nearest)/c
        arrival_hi = track.time[i+1]+np.linalg.norm(farthest)/c
        tolerance = max(1e-7, 4*abs(np.spacing(max(abs(arrival_lo), abs(arrival_hi)))))
        envelopes.append(([float(track.time[i]), float(track.time[i+1])],
                          [arrival_lo-tolerance, arrival_hi+tolerance]))
    return envelopes


def check_query(track, query, observer, c, envelopes):
    expected = [(emission, arrival) for emission, arrival in envelopes
                if np.any((query >= arrival[0]) & (query <= arrival[1]))]
    try:
        track._check_motion_support(query, observer, c)
    except geometry.AcousticSupportError as error:
        assert expected
        assert error.track_id == track.id and error.reason == "non_subsonic_motion"
        assert error.emission_intervals_s == [row[0] for row in expected]
        assert error.receive_intervals_s == [[float(value) for value in row[1]] for row in expected]
    else:
        assert not expected


def check_recorded_motion_extrema(relative):
    for track in observed_tracks(relative):
        original = deepcopy(track)
        for c in (343., 338., 348., 600., 1000., 343.):
            assert np.array_equal(track._unsupported_motion_intervals(c), original_indices(original, c))
            assert np.array_equal(track._speed_peak, original._speed_peak, equal_nan=True)


def check_recorded_arrival_bounds(relative):
    for track in observed_tracks(relative):
        for c in (338., 343., 348., 1000.):
            for location in (0, len(track.time)//2, -1):
                observer = geometry.ecef(track.lat[location], track.lon[location], 0.)
                envelopes = original_envelopes(track, observer, c)
                receive = track.time+np.linalg.norm(track.xyz-observer, axis=1)/c
                receive.setflags(write=False)
                for query in (receive, receive[::-1], receive[len(receive)//2], receive[:0],
                              receive[:len(receive)//2*2].reshape(-1, 2),
                              np.r_[receive, receive[0], np.nan, np.inf, -np.inf]):
                    check_query(track, query, observer, c, envelopes)
                # Test each endpoint alone; a vector containing nearby interior
                # samples could otherwise hide an inclusive-boundary regression.
                for _, interval in envelopes:
                    for endpoint in interval:
                        for query in (np.nextafter(endpoint, -np.inf), endpoint,
                                      np.nextafter(endpoint, np.inf)):
                            check_query(track, query, observer, c, envelopes)


def check_recorded_interval_blocks():
    for track in observed_tracks():
        observer = geometry.ecef(track.lat[0], track.lon[0], 0.)
        receive = track.time+np.linalg.norm(track.xyz-observer, axis=1)/343.
        check_query(track, receive, observer, 343., original_envelopes(track, observer, 343.))


def check_recorded_numeric_precision():
    for track in observed_tracks():
        for dtype in (np.float32, np.float64, np.longdouble):
            observer = geometry.ecef(track.lat[0], track.lon[0], 0.).astype(dtype)
            for c in (np.float32(343), np.float64(343), np.longdouble(343)):
                envelopes = original_envelopes(track, observer, c)
                query = np.asarray([value for _, interval in envelopes for value in interval])
                query.setflags(write=False)
                check_query(track, query[::-1], observer, c, envelopes)


class RecordedMotionSupportTests(unittest.TestCase):
    def test_epoch_extrema_after_threshold_changes(self):
        check_recorded_motion_extrema(False)

    def test_relative_extrema_after_threshold_changes(self):
        check_recorded_motion_extrema(True)

    def test_epoch_arrival_boundaries_shapes_and_order(self):
        check_recorded_arrival_bounds(False)

    def test_relative_arrival_boundaries_shapes_and_order(self):
        check_recorded_arrival_bounds(True)

    def test_interval_block_boundaries(self):
        with patch.object(geometry, "_MOTION_SUPPORT_INTERVAL_BATCH", 2):
            check_recorded_interval_blocks()

    def test_scalar_numeric_precision(self):
        check_recorded_numeric_precision()


if __name__ == "__main__":
    unittest.main()
