"""Optional native propagation checks on archived aircraft observations."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd

from dopplergeist import geometry, native_acoustic
from dopplergeist.provenance import implementation_files
from dopplergeist.tracks import _segment_velocity


def _outcome(track, query, observer, c=343.):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            values = track.acoustic(query, observer, c)
            result = ("ok", tuple((a.dtype.str, a.shape, a.tobytes()) for a in values))
        except Exception as error:
            result = ("error", type(error).__name__, str(error), vars(error))
    return result, [(str(item.message), item.category.__name__) for item in caught]


def _clone(track):
    return geometry.Track(track.id, track.time.copy(), track.lat.copy(), track.lon.copy(),
        track.altitude.copy(), track.typecode,
        None if track.velocity is None else track.velocity.copy())


class NativeAcousticBackendTests(unittest.TestCase):
    def test_backend_selector_and_actual_binary_provenance(self):
        code = "from dopplergeist.geometry import ACOUSTIC_BACKEND; print(ACOUSTIC_BACKEND)"
        environment = dict(os.environ, DOPPLERGEIST_ACOUSTIC_BACKEND="python")
        python = subprocess.run([sys.executable, "-c", code], env=environment,
                                text=True, capture_output=True, check=True)
        self.assertEqual(python.stdout.strip(), "python-acoustic-v1")
        environment["DOPPLERGEIST_ACOUSTIC_BACKEND"] = "auto"
        automatic = subprocess.run([sys.executable, "-c", code], env=environment,
                                   text=True, capture_output=True, check=True)
        self.assertTrue(automatic.stdout.strip() == "python-acoustic-v1"
                        or automatic.stdout.strip().startswith("native-c-acoustic-v1:"))
        environment["DOPPLERGEIST_ACOUSTIC_BACKEND"] = "unknown"
        invalid = subprocess.run([sys.executable, "-c", code], env=environment,
                                 text=True, capture_output=True)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("DOPPLERGEIST_ACOUSTIC_BACKEND must be", invalid.stderr)
        if native_acoustic._native is not None:
            binary = Path(native_acoustic._native.__file__)
            self.assertIn(binary, implementation_files(binary.parent))


@unittest.skipIf(native_acoustic._native is None, "optional acoustic extension is not built")
class RealNativeAcousticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.tracks = []
        for source in sorted((root / "research/trajectory-motion/frozen").glob("fresh-*.json")):
            frame = pd.DataFrame(json.loads(source.read_text())).sort_values("time_s")
            for number, (_, rows) in enumerate(frame.groupby((frame.time_s.diff() > 30.).cumsum())):
                if len(rows) < 3:
                    continue
                velocity, _ = _segment_velocity(rows)
                cls.tracks.append(geometry.Track(f"{rows.flight_id.iloc[0]}:{number}",
                    rows.time_s.to_numpy(), rows.lat.to_numpy(), rows.lon.to_numpy(),
                    rows.alt_m.to_numpy(), str(rows.typecode.iloc[0]), velocity))
        cls.supported, cls.unsupported = [], []
        for track in cls.tracks:
            try:
                track.validate_motion_support()
                cls.supported.append(track)
            except geometry.AcousticSupportError:
                cls.unsupported.append(track)
        ridge = json.loads((root / "tests/data/real-ridge-batch-arithmetic.json").read_text())
        cls.ridge_times = np.asarray(ridge["times"])

    def assert_parity(self, track, query, observer, c=343.):
        with patch.object(native_acoustic, "_native", None):
            expected = _outcome(track, query, observer, c)
        actual = _outcome(track, query, observer, c)
        self.assertEqual(actual, expected)

    def test_recorded_queries_boundaries_and_global_newton_stop(self):
        self.assertTrue(self.supported)
        before = native_acoustic._native.successful_calls()
        for track in self.supported:
            for index in (0, len(track.time)//2, -1):
                observer = geometry.ecef(track.lat[index], track.lon[index], 0.)
                receive = track.time + np.linalg.norm(track.xyz-observer, axis=1)/343.
                endpoints = receive[[0, -1]]
                boundary = np.r_[np.nextafter(endpoints, -np.inf), endpoints,
                                  np.nextafter(endpoints, np.inf)]
                measured = receive[len(receive)//2] + self.ridge_times - np.median(self.ridge_times)
                readonly = receive.copy()
                readonly.flags.writeable = False
                for query in (receive, receive[1], receive[::-1], readonly, boundary,
                              measured, measured.reshape(1, -1), np.r_[receive, np.nan],
                              np.r_[receive, np.inf], receive[:0]):
                    for c in (338., 343., 348.):
                        self.assert_parity(track, query, observer, c)
        self.assertGreater(native_acoustic._native.successful_calls(), before)

    def test_unsupported_tracks_keep_error_details(self):
        self.assertTrue(self.unsupported)
        for track in self.unsupported:
            observer = geometry.ecef(track.lat[len(track.time)//2], track.lon[len(track.time)//2], 0.)
            receive = track.time + np.linalg.norm(track.xyz-observer, axis=1)/343.
            self.assert_parity(track, receive, observer)
        # An extreme sound-speed argument must retain NumPy overflow warnings,
        # even when an infinite intermediate would leave the final outputs NaN.
        track = self.supported[0]
        velocity = track.speed_vector(track.time[0])
        observer = track.xyz[0] - np.copysign(np.abs(np.spacing(track.xyz[0])), velocity)
        before = native_acoustic._native.successful_calls()
        self.assert_parity(track, track.time[0], observer, 1e-312)
        self.assertEqual(native_acoustic._native.successful_calls(), before)

    def test_noncanonical_policy_layout_and_method_overrides_fall_back(self):
        track = _clone(self.supported[0])
        observer = geometry.ecef(track.lat[0], track.lon[0], 0.)
        receive = track.time + np.linalg.norm(track.xyz-observer, axis=1)/343.
        for c in (np.float32(343.), np.longdouble(343.)):
            before = native_acoustic._native.successful_calls()
            # Longdouble storage can contain padding; compare numerical values.
            with patch.object(native_acoustic, "_native", None):
                expected = track.acoustic(receive, observer, c)
            actual = track.acoustic(receive, observer, c)
            for a, b in zip(expected, actual):
                self.assertEqual(a.dtype, b.dtype)
                self.assertTrue(np.array_equal(a, b, equal_nan=True))
            self.assertEqual(native_acoustic._native.successful_calls(), before)
        for policy in ("raise", "ignore"):
            before = native_acoustic._native.successful_calls()
            with np.errstate(all=policy):
                self.assert_parity(track, receive, observer)
            self.assertEqual(native_acoustic._native.successful_calls(), before)
        for name in ("position", "_position_velocity"):
            before = native_acoustic._native.successful_calls()
            with patch.object(track, name, wraps=getattr(track, name)) as wrapped:
                self.assert_parity(track, receive, observer)
                self.assertGreater(wrapped.call_count, 0)
            self.assertEqual(native_acoustic._native.successful_calls(), before)
        original_position = geometry.Track.position
        def position(self, query):
            return original_position(self, query)
        before = native_acoustic._native.successful_calls()
        with patch.object(geometry.Track, "position", position):
            self.assert_parity(track, receive, observer)
        self.assertEqual(native_acoustic._native.successful_calls(), before)
        for name, value in (("axis", 1), ("extrapolate", True)):
            before = native_acoustic._native.successful_calls()
            with patch.object(track.spline, name, value):
                self.assert_parity(track, receive, observer)
            self.assertEqual(native_acoustic._native.successful_calls(), before)
        # Read-only inputs are supported, while strided arrays take the reference path.
        before = native_acoustic._native.successful_calls()
        self.assert_parity(track, receive[::-1], observer)
        self.assertEqual(native_acoustic._native.successful_calls(), before)

    def test_cold_and_mutable_packed_spline_cache(self):
        a, b = (_clone(self.supported[0]) for _ in range(2))
        observer = geometry.ecef(a.lat[0], a.lon[0], 0.)
        receive = a.time + np.linalg.norm(a.xyz-observer, axis=1)/343.
        geometry._packed_kinematics.cache_clear()
        for mutation in ("none", "source", "packed", "layout"):
            for track in (a, b):
                if mutation == "source":
                    track.spline.c[3, 0, 0] = np.nextafter(track.spline.c[3, 0, 0], np.inf)
                elif mutation == "packed":
                    packed = geometry._packed_kinematics(track.spline, track.derivative)
                    packed.c[3, 0, 0] = np.nextafter(packed.c[3, 0, 0], np.inf)
                elif mutation == "layout":
                    track.spline.c = np.asfortranarray(track.spline.c)
                    track.time.flags.writeable = False
            with patch.object(native_acoustic, "_native", None):
                expected = _outcome(a, receive, observer)
            self.assertEqual(_outcome(b, receive, observer), expected)


if __name__ == "__main__":
    unittest.main()
