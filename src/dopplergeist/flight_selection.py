"""Select native traces without clipping the trajectories used by the index."""

import json

import numpy as np
import pandas as pd

from .data_access import _continuous_bounds, _frame_track


def intersects_index_query(frame, bounds, time_range, *, max_gap_s=30.0):
    """Whether any indexable segment's conservative envelope meets a query.

    The input must be the complete normalized trace. Match FlightIndex's valid
    row filtering, serialization precision, gap splitting and continuous bounds.
    The caller retains the *entire* original frame on a match, since trimming
    changes boundary derivatives and can create artificial track endpoints.
    """
    if frame.empty:
        return False
    valid = np.isfinite(frame[["time_s", "lat", "lon", "alt_m"]].to_numpy(dtype=float)).all(axis=1)
    valid &= frame.lat.between(-90, 90) & frame.lon.between(-180, 180) & frame.flight_id.notna()
    clean = frame.loc[valid]
    if clean.empty:
        return False
    # FlightIndex writes through JSON before deriving segment geometry.
    clean = pd.DataFrame(json.loads(clean.to_json(orient="records", double_precision=15)))
    west, south, east, north = bounds
    for flight, rows in clean.groupby("flight_id", sort=False):
        rows = rows.sort_values("time_s", kind="stable").drop_duplicates("time_s")
        groups = (rows.time_s.diff() > max_gap_s).cumsum()
        for _, chunk in rows.groupby(groups):
            if len(chunk) < 3:
                continue
            if time_range is not None and (chunk.time_s.iloc[0] > time_range[1] or
                                           chunk.time_s.iloc[-1] < time_range[0]):
                continue
            track = _frame_track(str(flight), chunk)
            seg_west, seg_east, seg_south, seg_north = _continuous_bounds(track)
            if seg_west <= east and seg_east >= west and seg_south <= north and seg_north >= south:
                return True
    return False
