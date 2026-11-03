"""Geometric event filters, silence constraints and locked multi-event scoring."""
from itertools import product

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from scipy.spatial import cKDTree

from .geometry import ecef


def cpa_table_dense(tracks, points, max_distance, c=343.0, step_s=2.0, chunk_size=256):
    """Vectorized piecewise-linear CPA prefilter; supports repeated local passes.

    This is the inexpensive first stage. Final scoring evaluates the interpolated
    trajectory and retarded emission time directly, rather than these CPA samples.
    """
    observers = ecef(points.lat.to_numpy(),points.lon.to_numpy(),points.elev_m.to_numpy())
    rows = []
    for track in tracks:
        t = np.unique(np.r_[np.arange(track.time[0],track.time[-1],step_s),track.time[-1]])
        pos = track.position(t)
        # Prune trajectory segments outside this observer tile before forming a
        # point-by-segment tensor. Keep original segment endpoints/times so a gap
        # between retained pieces cannot invent a straight-line flight.
        lower=observers.min(axis=0)-max_distance
        upper=observers.max(axis=0)+max_distance
        keep=np.all((np.minimum(pos[:-1],pos[1:])<=upper)&
                    (np.maximum(pos[:-1],pos[1:])>=lower),axis=1)
        if not np.any(keep):
            continue
        first,last=pos[:-1][keep],pos[1:][keep]
        t0,t1=t[:-1][keep],t[1:][keep]
        delta = last-first
        length2 = np.sum(delta**2,axis=1)
        endpoints=np.concatenate((first,last))
        near_box=np.all((observers>=endpoints.min(axis=0)-max_distance)&
                        (observers<=endpoints.max(axis=0)+max_distance),axis=1)
        nearby=np.flatnonzero(near_box)
        supported = np.isfinite(cKDTree(endpoints).query(observers[nearby],
            distance_upper_bound=max_distance+np.sqrt(length2.max()))[0])
        active=nearby[supported]
        for base in range(0,len(active),chunk_size):
            indices = active[base:base+chunk_size]
            obs = observers[indices]
            residual = first[None,:,:]-obs[:,None,:]
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
                    when = t0[k]+fraction[j,k]*(t1[k]-t0[k])
                    if distance > max_distance or when-last_time < step_s*1.1:
                        continue
                    last_time = when
                    rows.append({"point_id":int(points.iloc[indices[j]].point_id),"flight_id":track.id,
                                 "emission_time":when,"receive_time":when+distance/c,
                                 "distance_m":distance,
                                 "speed_mps":np.linalg.norm(track.speed_vector(when))})
    return pd.DataFrame(rows,columns=["point_id","flight_id","emission_time","receive_time","distance_m","speed_mps"])


def cpa_table(tracks,points,max_distance,c=343.0,step_s=2.0,chunk_size=512):
    """Spatial-radius CPA graph, retaining every local pass without dense tensors.

    The radius includes two complete sample steps beyond the audible envelope,
    so both neighbours of an in-range sampled minimum are present. Each minimum
    is refined on its two actual adjacent segments. The dense reference above
    provides an independent regression oracle for this search optimization.
    """
    observers=ecef(points.lat.to_numpy(),points.lon.to_numpy(),points.elev_m.to_numpy())
    point_ids=points.point_id.to_numpy(dtype=int)
    rows=[]
    for track in tracks:
        t=np.unique(np.r_[np.arange(track.time[0],track.time[-1],step_s),track.time[-1]])
        pos=track.position(t)
        max_step=np.max(np.linalg.norm(np.diff(pos,axis=0),axis=1))
        near=np.flatnonzero(np.all((observers>=pos.min(axis=0)-max_distance)&
                                  (observers<=pos.max(axis=0)+max_distance),axis=1))
        tree=cKDTree(pos)
        for base in range(0,len(near),chunk_size):
            chosen=near[base:base+chunk_size]
            obs=observers[chosen]
            neighbours=tree.query_ball_point(obs,max_distance+2*max_step,return_sorted=True)
            counts=np.fromiter((len(a) for a in neighbours),dtype=int,count=len(neighbours))
            if not counts.sum():continue
            sample=np.concatenate(neighbours).astype(int)
            observer_index=np.repeat(np.arange(len(obs)),counts)
            distance2=np.sum((pos[sample]-obs[observer_index])**2,axis=1)
            previous=np.r_[False,(observer_index[1:]==observer_index[:-1])&(sample[1:]==sample[:-1]+1)]
            following=np.r_[(observer_index[1:]==observer_index[:-1])&(sample[1:]==sample[:-1]+1),False]
            minima=(previous&following&(distance2<=np.r_[np.inf,distance2[:-1]])&
                    (distance2<np.r_[distance2[1:],np.inf]))
            indices=np.flatnonzero(minima)
            if not len(indices):continue
            k=sample[indices]
            oi=observer_index[indices]
            # Project onto both neighbouring polyline edges, never across a
            # missing interval or between unrelated flight passes.
            first=np.stack((pos[k-1],pos[k]),axis=1)
            last=np.stack((pos[k],pos[k+1]),axis=1)
            delta=last-first
            residual=first-obs[oi,None,:]
            fraction=np.clip(-np.sum(residual*delta,axis=2)/np.maximum(np.sum(delta**2,axis=2),1e-12),0,1)
            d2=np.sum((residual+fraction[:,:,None]*delta)**2,axis=2)
            edge=np.argmin(d2,axis=1)
            n=np.arange(len(k))
            distance=np.sqrt(d2[n,edge])
            start=np.where(edge==0,k-1,k)
            when=t[start]+fraction[n,edge]*(t[start+1]-t[start])
            speed=np.linalg.norm(track.speed_vector(when),axis=1)
            for j in np.flatnonzero(distance<=max_distance):
                rows.append({"point_id":int(point_ids[chosen[oi[j]]]),"flight_id":track.id,
                             "emission_time":float(when[j]),"receive_time":float(when[j]+distance[j]/c),
                             "distance_m":float(distance[j]),"speed_mps":float(speed[j])})
    result=pd.DataFrame(rows,columns=["point_id","flight_id","emission_time","receive_time","distance_m","speed_mps"])
    if not result.empty:
        # A CPA exactly at a sample can be proposed twice under roundoff.
        result=result.sort_values(["point_id","flight_id","emission_time"])
        duplicate=(result.point_id.eq(result.point_id.shift())&result.flight_id.eq(result.flight_id.shift())&
                   result.emission_time.diff().abs().lt(step_s*1.1))
        result=result[~duplicate].reset_index(drop=True)
    return result


def filter_event(table, event, time_origin=None, time_tolerance=5.0):
    speed, distance = event["speed_range_mps"],event["slant_range_m"]
    quality = event.get("quality", {})
    dv, dd = quality.get("speed_tolerance_mps", 0), quality.get("slant_tolerance_m", 0)
    dt = quality.get("cpa_tolerance_s", 0)
    if not all(np.isfinite(v) and v >= 0 for v in (dv, dd, dt)):
        raise ValueError("Proposal tolerances must be finite and nonnegative")
    keep = table.speed_mps.between(max(0, speed[0]-dv), speed[1]+dv) & table.distance_m.between(max(0, distance[0]-dd), distance[1]+dd)
    if time_origin is not None:
        keep &= np.abs(table.receive_time-(time_origin+event["cpa_receive_s"])) <= time_tolerance + dt
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
            starts = np.array([row["receive_time"]-event["cpa_receive_s"] for row,event in zip(combination,events)])
            tolerance = np.array([event.get("quality", {}).get("cpa_tolerance_s", 0) for event in events]) + offset_tolerance_s/2
            lower, upper = float(np.max(starts-tolerance)), float(np.min(starts+tolerance))
            if time_origin is not None:
                lower, upper = max(lower,time_origin-time_tolerance_s), min(upper,time_origin+time_tolerance_s)
            if lower > upper:
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
                for selected in combination:
                    is_selected = (between.flight_id.eq(selected["flight_id"]) &
                                   between.emission_time.eq(selected["emission_time"]))
                    between = between.loc[~is_selected]
                if len(between):
                    rejected += 1
                    continue
            candidates.append({"point_id":point_id,"passes":combination,
                               "recording_start_bounds_s":[lower,upper]})
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
    association = "event_indices" in candidate
    association_fields = {}
    if association:
        if mode != "robust_ridge":
            raise ValueError("Partial-event association requires robust_ridge scoring")
        indices = candidate["event_indices"]
        if not indices or indices != sorted(set(indices)) or any(i < 0 or i >= len(events) for i in indices):
            raise ValueError("Association event indices must be unique, ordered and in range")
        association_fields = {"event_indices": indices,
            "event_ids": [events[i].get("event_id", str(i)) for i in indices],
            "unmatched_event_ids": [e.get("event_id", str(i)) for i, e in enumerate(events) if i not in indices]}
        events, measurements = [events[i] for i in indices], [measurements[i] for i in indices]
    if not events or len(events) != len(measurements) or len(events) != len(candidate["passes"]):
        raise ValueError("Need exactly one pass and measurement for each event")
    if mode not in ("brightness", "ridge", "robust_ridge"):
        raise ValueError(f"Unknown scoring mode: {mode}")
    if time_step_s <= 0 or time_sweep_s < 0:
        raise ValueError("Need positive clock step and nonnegative sweep")
    observer = ecef(point.lat,point.lon,point.elev_m)
    # Derive one recording start from the first event; all other events retain
    # their true absolute geometry/time. This implements the locked offset.
    anchor = time_origin if time_origin is not None else candidate["passes"][0]["receive_time"]-events[0]["cpa_receive_s"]
    shifts = np.linspace(-time_sweep_s,time_sweep_s,max(1,int(np.ceil(2*time_sweep_s/time_step_s)))+1)
    if mode == "robust_ridge" and "recording_start_bounds_s" in candidate:
        lower, upper = candidate["recording_start_bounds_s"]
        # CPA intervals propose a shared clock; the physical model may move it
        # within the same declared sweep used by legacy scoring.
        lower, upper = lower-time_sweep_s, upper+time_sweep_s
        if time_origin is not None:
            lower, upper = max(lower,anchor-time_sweep_s), min(upper,anchor+time_sweep_s)
        if lower > upper:
            shifts = []
        else:
            shifts = np.linspace(lower-anchor,upper-anchor,max(1,int(np.ceil((upper-lower)/time_step_s)))+1)
    best = {"score":-np.inf}
    for shift in shifts:
        if mode == "robust_ridge":
            from .matching import score_ridges
            result = score_ridges([tracks[p["flight_id"]] for p in candidate["passes"]],
                                  events,measurements,observer,anchor+shift,c)
            if association:
                from .matching import association_score
                result = association_score(result, events)
            if result["score"] > best["score"]:
                best = dict(result,recording_start_time_s=float(anchor+shift),time_adjustment_s=float(shift))
            continue
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
    return dict(best,**association_fields,point_id=int(point.point_id),lat=float(point.lat),lon=float(point.lon),elev_m=float(point.elev_m),
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
