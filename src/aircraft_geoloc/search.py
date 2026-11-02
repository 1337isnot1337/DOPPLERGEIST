"""Geometric event filters, silence constraints and locked multi-event scoring."""
from itertools import product

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from scipy.spatial import cKDTree

from .geometry import ecef


def cpa_table(tracks, points, max_distance, c=343.0, step_s=2.0, chunk_size=256):
    """Vectorized piecewise-linear CPA prefilter; supports repeated local passes.

    This is the inexpensive first stage. Final scoring evaluates the interpolated
    trajectory and retarded emission time directly, rather than these CPA samples.
    """
    observers = ecef(points.lat.to_numpy(),points.lon.to_numpy(),points.elev_m.to_numpy())
    rows = []
    for track in tracks:
        t = np.unique(np.r_[np.arange(track.time[0],track.time[-1],step_s),track.time[-1]])
        pos = track.position(t)
        delta = np.diff(pos,axis=0)
        length2 = np.sum(delta**2,axis=1)
        supported = np.isfinite(cKDTree(pos).query(observers,
            distance_upper_bound=max_distance+np.sqrt(length2.max()))[0])
        for base in range(0,len(points),chunk_size):
            indices = np.flatnonzero(supported[base:base+chunk_size])+base
            if not len(indices):
                continue
            obs = observers[indices]
            residual = pos[:-1][None,:,:]-obs[:,None,:]
            fraction = np.clip(-np.einsum("bsi,si->bs",residual,delta)/np.maximum(length2,1e-12),0,1)
            dist2 = np.sum((residual+fraction[:,:,None]*delta[None,:,:])**2,axis=2)
            # A zero-velocity segment or path endpoint is not evidence of a full
            # flyover. Keep interior minima and deduplicate adjoining segments.
            for j in range(len(obs)):
                peaks = find_peaks(-dist2[j],plateau_size=1)[0]
                if len(dist2[j]) > 2:
                    global_i = int(np.argmin(dist2[j]))
                    if 0 < global_i < len(dist2[j])-1:
                        peaks = np.unique(np.r_[peaks,global_i])
                last_time = -np.inf
                for k in peaks:
                    distance = np.sqrt(dist2[j,k])
                    when = t[k]+fraction[j,k]*(t[k+1]-t[k])
                    if distance > max_distance or when-last_time < step_s*1.1:
                        continue
                    last_time = when
                    rows.append({"point_id":int(points.iloc[indices[j]].point_id),"flight_id":track.id,
                                 "emission_time":when,"receive_time":when+distance/c,
                                 "distance_m":distance,
                                 "speed_mps":np.linalg.norm(track.speed_vector(when))})
    return pd.DataFrame(rows,columns=["point_id","flight_id","emission_time","receive_time","distance_m","speed_mps"])


def filter_event(table, event, time_origin=None, time_tolerance=5.0):
    speed, distance = event["speed_range_mps"],event["slant_range_m"]
    keep = table.speed_mps.between(*speed) & table.distance_m.between(*distance)
    if time_origin is not None:
        keep &= np.abs(table.receive_time-(time_origin+event["cpa_receive_s"])) <= time_tolerance
    return table.loc[keep]


def pair_candidates(table, events, offset_tolerance_s=5.0, time_origin=None,
                    time_tolerance_s=5.0, silence=None):
    filtered = [filter_event(table,event,time_origin,time_tolerance_s) for event in events]
    if any(frame.empty for frame in filtered):
        return [],{"per_event_survivors":[len(f) for f in filtered],"pairs_before_silence":0,"silence_rejected":0}
    group = [dict(tuple(frame.groupby("point_id"))) for frame in filtered]
    common = set.intersection(*(set(g) for g in group))
    all_by_point = dict(tuple(table.groupby("point_id")))
    candidates, before, rejected = [],0,0
    for point_id in sorted(common):
        for combination in product(*(list(g[point_id].to_dict("records")) for g in group)):
            anchor = combination[0]["receive_time"]
            if any(abs((row["receive_time"]-anchor)-(events[i]["cpa_receive_s"]-events[0]["cpa_receive_s"]))
                   > offset_tolerance_s for i,row in enumerate(combination[1:],1)):
                continue
            if len(combination)>1 and len({(r["flight_id"],round(r["emission_time"],1)) for r in combination})<len(combination):
                continue
            before += 1
            if silence and len(combination)>1:
                threshold = max(row["distance_m"] for row in combination)*silence.get("distance_multiplier",1.0)
                margin = silence.get("edge_margin_s",60)
                between = all_by_point[point_id]
                between = between[(between.receive_time>anchor+margin)&
                                  (between.receive_time<combination[-1]["receive_time"]-margin)&
                                  (between.distance_m<=threshold)]
                # Only the selected actual passes are excluded, not every future
                # pass by an aircraft with the same flight ID.
                if len(between):
                    rejected += 1
                    continue
            candidates.append({"point_id":point_id,"passes":combination})
    return candidates,{"per_event_survivors":[len(f) for f in filtered],
                       "pairs_before_silence":before,"silence_rejected":rejected,"survivors":len(candidates)}


def event_score(track, observer, spectrum, ridge, weight, start_time, f0_bounds, mode, c=343.0,
                frequency_step=0.2):
    # The same receiver-clock time is used for all events. No per-event time fit.
    times = spectrum.time
    factor,_,_ = track.acoustic(start_time+times,observer,c)
    valid = np.isfinite(factor)
    if np.mean(valid)<0.95:
        return -np.inf,np.nan
    if mode=="ridge":
        valid &= np.isfinite(ridge)
        if np.sum(valid)<10:
            return -np.inf,np.nan
        w = np.maximum(np.asarray(weight)[valid],0.05)
        f0 = np.clip(np.sum(w*factor[valid]*ridge[valid])/np.sum(w*factor[valid]**2),*f0_bounds)
        rmse = np.sqrt(np.average((f0*factor[valid]-ridge[valid])**2,weights=w))
        return -float(rmse),float(f0)
    frequencies = np.linspace(*f0_bounds,max(3,int(np.ceil((f0_bounds[1]-f0_bounds[0])/frequency_step))+1))
    predicted = frequencies[:,None]*factor[None,:]
    contrast = spectrum.sample(times[None,:],predicted)
    # Fixed support: candidates do not gain points by leaving the frequency band.
    scores = np.where(np.mean(np.isfinite(contrast),axis=1)>=0.95,
                      np.mean(np.nan_to_num(contrast,nan=-4.0),axis=1),-np.inf)
    best = np.argmax(scores)
    return float(scores[best]),float(frequencies[best])


def score_candidate(candidate, point, tracks, events, measurements, mode="brightness",
                    time_origin=None, time_sweep_s=5.0, time_step_s=0.5, c=343.0):
    observer = ecef(point.lat,point.lon,point.elev_m)
    # Derive one recording start from the first event; all other events retain
    # their true absolute geometry/time. This implements the locked offset.
    anchor = time_origin if time_origin is not None else candidate["passes"][0]["receive_time"]-events[0]["cpa_receive_s"]
    shifts = np.linspace(-time_sweep_s,time_sweep_s,max(1,int(np.ceil(2*time_sweep_s/time_step_s)))+1)
    best = {"score":-np.inf}
    for shift in shifts:
        scores,f0s = [],[]
        for event,measurement,flyover in zip(events,measurements,candidate["passes"]):
            spec,ridge,weight,_ = measurement
            score,f0 = event_score(tracks[flyover["flight_id"]],observer,spec,ridge,weight,
                                   anchor+shift,event["f0_range_hz"],mode,c,event.get("frequency_step_hz",0.2))
            scores.append(score)
            f0s.append(f0)
        total = float(np.sum(scores))
        if total>best["score"]:
            best = {"score":total,"event_scores":scores,"f0_hz":f0s,
                    "recording_start_time_s":float(anchor+shift),"time_adjustment_s":float(shift)}
    return dict(best,point_id=int(point.point_id),lat=float(point.lat),lon=float(point.lon),elev_m=float(point.elev_m),
                x=float(point.x),y=float(point.y),flight_ids=[p["flight_id"] for p in candidate["passes"]])


def rank_candidates(candidates, points, tracks, events, measurements, **kwargs):
    lookup = {row.point_id:row for row in points.itertuples()}
    track_lookup = {track.id:track for track in tracks}
    result = []
    for i,candidate in enumerate(candidates):
        row = score_candidate(candidate,lookup[candidate["point_id"]],track_lookup,events,measurements,**kwargs)
        if np.isfinite(row["score"]):
            result.append(row)
        if i and i%100==0:
            print(f"Scored {i}/{len(candidates)} candidates",flush=True)
    return sorted(result,key=lambda r:r["score"],reverse=True)
