"""Unit fixtures for all-event association; not blind/national accuracy evidence."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer

from aircraft_geoloc.geometry import Track, ecef, straight_doppler
from aircraft_geoloc.matching import RidgeTimes, association_candidates, refine_candidate
from aircraft_geoloc.search import score_candidate


class TonePass:
    def __init__(self, center):
        self.center = center

    def acoustic(self, times, observer, c):
        times = np.asarray(times)
        return 1.1-0.25*np.tanh((times-self.center)/8), times-5, np.full_like(times, 1700)


@pytest.mark.parametrize("count", [3, 4, 6])
def test_all_supported_events_survive_a_leading_distractor(count):
    tracks, events, measurements, rows = {}, [], [], []
    for i in range(count+1):
        center, identity = 30+180*i, f"track-{i}"
        track = tracks[identity] = TonePass(center)
        times = np.arange(center-25, center+25, 1.0)
        ridge = 120*track.acoustic(times, None, 343)[0]
        if i == 0:
            ridge = np.random.default_rng(19).uniform(90, 160, len(times))
        events.append(dict(event_id=f"event-{i}", cpa_receive_s=center, f0_range_hz=[119, 121],
                           speed_range_mps=[60, 100], slant_range_m=[500, 3000]))
        measurements.append((RidgeTimes(times), ridge, np.ones(len(times)), {}))
        rows.append(dict(point_id=0, flight_id=identity, receive_time=center, emission_time=center-5,
                         distance_m=1700, speed_mps=80))
    candidates, counts = association_candidates(pd.DataFrame(rows), events, time_origin=0)
    point = SimpleNamespace(point_id=0, lat=40, lon=-100, elev_m=100, x=0, y=0)
    ranked = [score_candidate(c, point, tracks, events, measurements, mode="robust_ridge",
                              time_origin=0, time_sweep_s=0) for c in candidates]
    best = max(ranked, key=lambda row: row["score"])
    assert best["event_indices"] == list(range(1, count+1))
    assert best["unmatched_event_ids"] == ["event-0"]
    assert len(best["event_diagnostics"]) == count
    assert abs(best["score"]-count) < 1e-7
    assert counts["max_matched_events"] == count+1
    assert not counts["event_cap_limited"]
    final = tracks[f"track-{count}"]
    tracks[f"track-{count}"] = TonePass(final.center+8)
    altered = score_candidate(next(c for c in candidates if c["event_indices"] == best["event_indices"]),
        point, tracks, events, measurements, mode="robust_ridge", time_origin=0, time_sweep_s=0)
    assert altered["score"] < best["score"]-0.1


@pytest.mark.parametrize("count", [3, 4, 6])
def test_every_event_enters_joint_physical_refinement(count):
    observer, epoch = ecef(40, -100, 100), 1_790_000_000.0
    lat, lon = np.deg2rad([40, -100])
    east = np.array([-np.sin(lon), np.cos(lon), 0])
    north = np.array([-np.sin(lat)*np.cos(lon), -np.sin(lat)*np.sin(lon), np.cos(lat)])
    up = np.array([np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)])
    inverse = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)
    tracks, events, measurements = {}, [], []
    for i in range(count):
        center, f0, angle = 70+180*i, 120+10*i, 0.4+0.9*i
        velocity = 80*(np.cos(angle)*east+np.sin(angle)*north)
        cross = 1300*(-np.sin(angle)*east+np.cos(angle)*north)+(900+100*i)*up
        times = np.arange(center-100, center+101, 1.0)
        xyz = observer+(times-center)[:, None]*velocity+cross
        track_lon, track_lat, height = inverse.transform(*xyz.T)
        identity = f"physical-{i}"
        tracks[identity] = Track(identity, times+epoch, track_lat, track_lon, height,
                                 velocity=np.tile(velocity, (len(times), 1)))
        receive = np.arange(center-35, center+35, 1.0)
        slant = np.linalg.norm(cross)
        ridge = straight_doppler(receive, f0, 80, slant, center+slant/343)
        measurements.append((RidgeTimes(receive), ridge, np.ones(len(receive)), {}))
        events.append(dict(f0_range_hz=[f0-1, f0+1], quality={"source_drift_fraction": 0}))
    candidate = dict(lat=40.0015, lon=-99.998, elev_m=100, recording_start_time_s=epoch,
                     flight_ids=list(tracks), event_indices=list(range(count)))
    terrain = SimpleNamespace(sample=lambda lat, lon: np.array(100.0))
    kwargs = dict(recording_start_window_s=(epoch, epoch), altitude_offsets_m=(0.0,))
    result = refine_candidate(candidate, tracks, events, measurements, terrain, **kwargs)
    assert len(result["event_diagnostics"]) == count
    assert np.linalg.norm(ecef(result["lat"], result["lon"], 100)-observer) < 10
    changed = list(measurements)
    spec, ridge, weight, fit = changed[-1]
    changed[-1] = (spec, ridge+0.6*np.linspace(-1, 1, len(ridge)), weight, fit)
    moved = refine_candidate(candidate, tracks, events, changed, terrain, **kwargs)
    # Exact earlier passes can pin the location despite an inconsistent final
    # pass. Its residual must still enter the refined objective and diagnostics.
    assert moved["event_diagnostics"][-1]["rmse_hz"] > 0.1
    assert moved["score"] < result["score"]
    assert moved["recording_start_time_s"] == epoch
    changed_first = list(measurements)
    spec, ridge, weight, fit = changed_first[0]
    changed_first[0] = (spec, ridge+0.6*np.linspace(-1, 1, len(ridge)), weight, fit)
    prefix = dict(candidate, flight_ids=candidate["flight_ids"][:1], event_indices=[0])
    early = refine_candidate(prefix, tracks, events, changed_first, terrain, **kwargs)
    joint = refine_candidate(candidate, tracks, events, changed_first, terrain, **kwargs)
    early_error = np.linalg.norm(ecef(early["lat"], early["lon"], 100)-observer)
    joint_error = np.linalg.norm(ecef(joint["lat"], joint["lon"], 100)-observer)
    assert early_error > 1
    assert joint_error < early_error


def test_explicit_event_cap_and_large_index_are_never_silent():
    rows = [dict(point_id=0, flight_id=str(i), receive_time=30+100*i, emission_time=25+100*i,
                 speed_mps=80, distance_m=1700) for i in range(6)]
    events = [dict(cpa_receive_s=30+100*i, speed_range_mps=[60, 100], slant_range_m=[500, 3000]) for i in range(6)]
    _, counts = association_candidates(pd.DataFrame(rows), events, time_origin=0, max_events=3)
    assert counts["event_cap_limited"]
    with pytest.raises(ValueError, match="work/storage budget exceeded"):
        association_candidates(pd.DataFrame(rows*100), events, time_origin=0, max_candidates=2)


@pytest.mark.parametrize("origin", [None, 90])
def test_temporal_pruning_matches_an_exhaustive_small_oracle(origin):
    from itertools import combinations, product
    from aircraft_geoloc.search import filter_event
    rows = [dict(point_id=p, flight_id=str(i%2), receive_time=t, emission_time=t-5,
                 speed_mps=80, distance_m=1700) for p in (0, 1) for i, t in enumerate((100, 109, 121, 136))]
    table = pd.DataFrame(rows)
    events = [dict(cpa_receive_s=t, speed_range_mps=[60, 100], slant_range_m=[500, 3000],
                   quality={"cpa_tolerance_s": i/2}) for i, t in enumerate((10, 20, 30))]
    candidates, _ = association_candidates(table, events, time_origin=origin, time_tolerance_s=4,
                                          offset_tolerance_s=4)
    def key(point, indices, passes):
        return point, tuple(indices), tuple((p["flight_id"], p["emission_time"]) for p in passes)
    actual = {key(c["point_id"], c["event_indices"], c["passes"]) for c in candidates}
    expected = set()
    filtered = [filter_event(table, event, origin, 4) for event in events]
    for count in (1, 2, 3):
        for indices in combinations(range(3), count):
            for point in (0, 1):
                choices = [frame[frame.point_id == point].to_dict("records") for frame in (filtered[i] for i in indices)]
                for passes in product(*choices):
                    if len({(p["flight_id"], p["emission_time"]) for p in passes}) != count:
                        continue
                    starts = [p["receive_time"]-events[i]["cpa_receive_s"] for p, i in zip(passes, indices)]
                    tolerance = [2+events[i]["quality"]["cpa_tolerance_s"] for i in indices]
                    lo = max(s-d for s, d in zip(starts, tolerance))
                    hi = min(s+d for s, d in zip(starts, tolerance))
                    if origin is not None:
                        lo, hi = max(lo, origin-4), min(hi, origin+4)
                    if lo <= hi:
                        expected.add(key(point, indices, passes))
    assert actual == expected
