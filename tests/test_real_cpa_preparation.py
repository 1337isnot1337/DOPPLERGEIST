"""CPA preparation reuse on unchanged archived aircraft observations."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from dopplergeist import search
from dopplergeist.geometry import AcousticSupportError, Track, ecef
from dopplergeist.tracks import _segment_velocity


class RealCPAPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tracks = []
        root = Path(__file__).resolve().parents[1]
        for source in sorted((root / "research/trajectory-motion/frozen").glob("fresh-*.json")):
            frame = pd.DataFrame(json.loads(source.read_text())).sort_values("time_s")
            for number, (_, rows) in enumerate(frame.groupby((frame.time_s.diff() > 30.).cumsum())):
                if len(rows) < 3:
                    continue
                velocity, _ = _segment_velocity(rows)
                cls.tracks.append(Track(f"{rows.flight_id.iloc[0]}:{number}", rows.time_s.to_numpy(),
                    rows.lat.to_numpy(), rows.lon.to_numpy(), rows.alt_m.to_numpy(),
                    str(rows.typecode.iloc[0]), velocity))
        cls.supported, cls.unsupported = [], []
        for track in cls.tracks:
            try:
                track.validate_motion_support()
                cls.supported.append(track)
            except AcousticSupportError:
                cls.unsupported.append(track)
        cls.long_track = next(track for track in cls.supported if track.time[-1]-track.time[0] > 800.)

    def test_one_sampling_and_tree_for_several_real_receiver_chunks(self):
        track = self.long_track
        indices = np.linspace(1, len(track.time)-2, 24, dtype=int)
        observers = ecef(track.lat[indices], track.lon[indices], np.zeros(len(indices)))
        point_ids = np.arange(len(indices))
        for step in (np.float32(2), np.float64(2), np.longdouble(2)):
            chunks = [(observers[first:first+4], point_ids[first:first+4]) for first in range(0, len(indices), 4)]
            expected = [search._cpa_rows([track], points, ids, 20000., 343., step) for points, ids in chunks]
            with patch.object(track, "position", wraps=track.position) as position, \
                    patch.object(search, "cKDTree", wraps=search.cKDTree) as tree:
                prepared = search._PreparedCPATrack(track, 343., step)
                actual = [search._ordered_cpa_rows(prepared.raw_rows(points, ids, 20000.), step)
                          for points, ids in chunks]
            self.assertEqual(expected, actual)
            self.assertGreater(sum(map(len, actual)), 0)
            self.assertEqual(tree.call_count, 1)
            sampled = [call for call in position.call_args_list
                       if np.asarray(call.args[0]).ndim == 1 and len(np.asarray(call.args[0])) > 3]
            self.assertEqual(len(sampled), 1)

    def test_tree_stays_lazy_for_distant_recorded_receiver(self):
        track = self.long_track
        distant = next(other for other in self.supported if abs(other.lon[0]-track.lon[0]) > 3.)
        far = ecef(distant.lat[:1], distant.lon[:1], np.zeros(1))
        midpoint = len(track.time)//2
        near = ecef(track.lat[midpoint:midpoint+1], track.lon[midpoint:midpoint+1], np.zeros(1))
        prepared = search._PreparedCPATrack(track, 343., 2.)
        self.assertIsNone(prepared.tree)
        self.assertEqual(prepared.raw_rows(far, np.array([0]), 20000.), [])
        self.assertIsNone(prepared.tree)
        self.assertTrue(prepared.raw_rows(near, np.array([1]), 20000.))
        tree = prepared.tree
        self.assertIsNotNone(tree)
        self.assertEqual(prepared.raw_rows(far, np.array([2]), 20000.), [])
        self.assertIs(prepared.tree, tree)

    def test_unsupported_motion_keeps_original_error(self):
        self.assertTrue(self.unsupported)
        for track in self.unsupported:
            with self.assertRaises(AcousticSupportError) as direct:
                track.validate_motion_support()
            with self.assertRaises(AcousticSupportError) as prepared:
                search._PreparedCPATrack(track, 343., 2.)
            self.assertEqual(vars(direct.exception), vars(prepared.exception))


if __name__ == "__main__":
    unittest.main()
