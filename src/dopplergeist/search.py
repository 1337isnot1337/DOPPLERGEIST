"""Geometric event filters, silence constraints and locked multi-event scoring."""
from itertools import product
import math

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.signal import find_peaks
from scipy.spatial import cKDTree

from .geometry import AcousticSupportError, ecef


def cpa_table_dense(tracks, points, max_distance, c=343.0, step_s=2.0, chunk_size=256):
    """Vectorized piecewise-linear CPA prefilter; supports repeated local passes.

    This is the inexpensive first stage. Final scoring evaluates the interpolated
    trajectory and retarded emission time directly, rather than these CPA samples.
    """
    observers = ecef(points.lat.to_numpy(),points.lon.to_numpy(),points.elev_m.to_numpy())
    rows = []
    for track in tracks:
        track.validate_motion_support(c)
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
        track.validate_motion_support(c)
        t=np.unique(np.r_[np.arange(track.time[0],track.time[-1],step_s),track.time[-1]])
        pos=track.position(t)
        max_step=np.max(np.linalg.norm(np.diff(pos,axis=0),axis=1))
        near=np.flatnonzero(np.all((observers>=pos.min(axis=0)-max_distance)&
                                  (observers<=pos.max(axis=0)+max_distance),axis=1))
        if not len(near):continue
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
            # An endpoint sample can be the sampled minimum even when the
            # continuous spline turns strictly inside its adjacent interval.
            # Check the endpoint range-rate signs before optimizing the actual
            # spline; an endpoint alone is not evidence of a complete pass.
            eligible = np.flatnonzero(counts >= 2)
            ends = np.cumsum(counts)[eligible]
            starts = ends - counts[eligible]
            for end in (False, True):
                edge_indices = ends - 1 if end else starts
                adjacent = edge_indices - 1 if end else edge_indices + 1
                mask = ((sample[edge_indices] == (len(t)-1 if end else 0))
                        & (previous[edge_indices] if end else following[edge_indices])
                        & (distance2[edge_indices] <= distance2[adjacent]))
                oi_edge = eligible[mask]
                if not len(oi_edge):
                    continue
                lo, hi = (t[-2], t[-1]) if end else (t[0], t[1])
                endpoints = pos[[-2, -1]] if end else pos[[0, 1]]
                velocities = track.speed_vector(np.array([lo, hi]))
                radial_start = np.sum((endpoints[0] - obs[oi_edge]) * velocities[0], axis=1)
                radial_end = np.sum((endpoints[1] - obs[oi_edge]) * velocities[1], axis=1)
                for j in np.flatnonzero((radial_start < 0) & (radial_end > 0)):
                    observer = obs[oi_edge[j]]
                    fit = minimize_scalar(lambda dt: np.sum((track.position(lo + dt) - observer) ** 2),
                                          bounds=(0, hi-lo), method="bounded", options={"xatol": 0.001})
                    when = lo + fit.x
                    if not fit.success or not lo < when < hi or not np.isfinite(fit.fun):
                        raise AcousticSupportError(track.id, "cpa_endpoint_solver_not_converged",
                                                   emission_intervals_s=[[float(lo), float(hi)]])
                    distance = np.sqrt(fit.fun)
                    if distance <= max_distance:
                        rows.append({"point_id": int(point_ids[chosen[oi_edge[j]]]), "flight_id": track.id,
                                     "emission_time": float(when), "receive_time": float(when + distance/c),
                                     "distance_m": float(distance),
                                     "speed_mps": float(np.linalg.norm(track.speed_vector(when)))})
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


def filter_association_event(table, event, offset_tolerance_s, time_origin, time_tolerance_s):
    """Filter with the same shared-clock interval used by association."""
    frame = filter_event(table, event)
    if time_origin is not None:
        start = frame.receive_time - event["cpa_receive_s"]
        tolerance = event.get("quality", {}).get("cpa_tolerance_s", 0) + offset_tolerance_s/2
        frame = frame[(start - tolerance <= time_origin + time_tolerance_s) &
                      (start + tolerance >= time_origin - time_tolerance_s)]
    return frame


def pair_candidates(table, events, offset_tolerance_s=5.0, time_origin=None,
                    time_tolerance_s=5.0, silence=None):
    filtered = [filter_association_event(table, event, offset_tolerance_s, time_origin, time_tolerance_s)
                for event in events]
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
    from .spectral_grid import best_frequency
    return best_frequency(spectrum, times, factor, f0_bounds, frequency_step)


def _ridge_trial_classification(result, events, association):
    """Classify recorded core fits, without changing their score or rejection rule.

    Missing support and numerical failures are unknown. A supported finite fit
    can be rejected only by the existing association residual thresholds.
    """
    def finite(value):
        if type(value) is float:
            return math.isfinite(value)
        return (isinstance(value, (int, float, np.integer, np.floating))
                and not isinstance(value, (bool, np.bool_)) and np.isfinite(value))

    diagnostics = result.get("event_diagnostics")
    scores, frequencies = result.get("event_scores"), result.get("f0_hz")
    if (not isinstance(diagnostics, list) or not isinstance(scores, list) or not isinstance(frequencies, list)
            or not len(diagnostics) == len(scores) == len(frequencies) == len(events)):
        return "unknown", "missing_event_fit_evidence"
    fields = ("score", "f0_hz", "source_drift_hz", "source_drift_hz_s",
              "source_reference_emission_time_s", "source_span_s", "drift_bound_hz", "rmse_hz", "outlier_fraction")
    for diagnostic, score, frequency, event in zip(diagnostics, scores, frequencies, events):
        if (not isinstance(diagnostic, dict) or not finite(diagnostic.get("support_fraction"))
                or diagnostic["support_fraction"] != 1.0):
            return "unknown", "incomplete_acoustic_support"
        if (not all(finite(diagnostic.get(name)) for name in fields)
                or not finite(score) or not finite(frequency)):
            return "unknown", "nonfinite_fit_evidence"
        count, independent = diagnostic.get("sample_count"), diagnostic.get("independent_sample_count")
        if (type(count) is not int or type(independent) is not int or not 1 <= independent <= count
                or count < 10 or diagnostic["source_span_s"] <= 0 or diagnostic["drift_bound_hz"] < 0
                or diagnostic["rmse_hz"] < 0 or not 0 <= diagnostic["outlier_fraction"] <= 1
                or diagnostic["f0_hz"] <= 0 or diagnostic["score"] > 0):
            return "unknown", "invalid_fit_evidence"
        if "optimizer_success" in diagnostic and diagnostic["optimizer_success"] is not True:
            return "unknown", "failed_optimizer"
        if score != diagnostic["score"] or frequency != diagnostic["f0_hz"]:
            return "unknown", "inconsistent_event_fit_evidence"
        bounds = event.get("f0_range_hz")
        fraction = event.get("quality", {}).get("source_drift_fraction", 0.02)
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                or not all(finite(value) for value in bounds) or not 0 < bounds[0] <= bounds[1]
                or not bounds[0] <= frequency <= bounds[1]
                or not finite(fraction) or not 0 <= fraction <= 0.1):
            return "unknown", "fit_outside_declared_frequency_domain"
        drift, cap = diagnostic["source_drift_hz"], diagnostic["drift_bound_hz"]
        if not bounds[0] * fraction <= cap <= bounds[1] * fraction or abs(drift) > cap:
            return "unknown", "fit_outside_declared_drift_domain"
        if abs(diagnostic["source_drift_hz_s"] * diagnostic["source_span_s"] - drift) > 1e-12 + 1e-12 * abs(drift):
            return "unknown", "inconsistent_source_drift"
    if "optimizer_success" in result and result["optimizer_success"] is not True:
        return "unknown", "failed_optimizer"
    residual = float(sum(scores))
    if not finite(residual):
        return "unknown", "nonfinite_residual_score"
    if not association:
        if (result.get("score_kind") == "negative_robust_ridge_loss_hz"
                and finite(result.get("score")) and result["score"] == residual):
            return "evaluated", None
        return "unknown", "inconsistent_residual_score"
    from .matching import _frequency_scale
    limits = [3 * _frequency_scale(event) for event in events]
    if (result.get("score_kind") != "matched_group_support_minus_normalized_residual"
            or not finite(result.get("residual_score")) or result["residual_score"] != residual
            or not all(finite(v) and v > 0 for v in limits)):
        return "unknown", "inconsistent_association_evidence"
    supported = all(-score <= limit for score, limit in zip(scores, limits))
    if supported:
        expected = float(sum(1 - (-score) / limit for score, limit in zip(scores, limits)))
        if finite(result.get("score")) and result["score"] == expected:
            return "evaluated", None
    elif result.get("score") == -np.inf:
        return "rejected", "association_residual_limit"
    return "unknown", "unexplained_association_score"



def _association_trial_bound(result, events):
    """Bound an incompletely supported association at one shared clock.

    The declared score is sum(1 - loss_i / limit_i), or -inf if any event
    fails its residual limit. Each nonnegative unknown loss contributes at
    most one. Only a fully validated core fit can tighten that ceiling or
    establish a residual rejection. Missing support is still unknown.
    """
    kind = "matched_group_support_minus_normalized_residual"
    if not events or not isinstance(result, dict) or result.get("score_kind") != kind:
        return None
    from .matching import _frequency_scale
    try:
        limits = [3 * _frequency_scale(event) for event in events]
    except (TypeError, ValueError, KeyError):
        return None
    if not all(np.isfinite(value) and value > 0 for value in limits):
        return None
    maximum = float(len(events))
    diagnostics, scores, frequencies = (result.get(name) for name in ("event_diagnostics", "event_scores", "f0_hz"))
    if (not all(isinstance(values, list) and len(values) == len(events)
                for values in (diagnostics, scores, frequencies))
            or result.get("optimizer_success", True) is not True):
        return maximum
    contributions = []
    for diagnostic, score, frequency, event, limit in zip(diagnostics, scores, frequencies, events, limits):
        single = {"score_kind": "negative_robust_ridge_loss_hz", "score": score,
                  "event_scores": [score], "f0_hz": [frequency], "event_diagnostics": [diagnostic]}
        classification, _ = _ridge_trial_classification(single, [event], False)
        if classification != "evaluated":
            contributions.append(1.0)
            continue
        if -score > limit:
            return -np.inf
        # Use the scorer's per-event arithmetic, then round every contribution
        # and positive accumulation upward. Subtracting losses from k instead
        # changes the operation order and can understate a floating-point score.
        contributions.append(float(np.nextafter(1 - (-score) / limit, np.inf)))
    upper = 0.0
    for contribution in contributions:
        upper = float(np.nextafter(upper + contribution, np.inf))
    return min(maximum, upper)


def score_candidate(candidate, point, tracks, events, measurements, mode="brightness",
                    time_origin=None, time_sweep_s=5.0, time_step_s=0.5, c=343.0,
                    score_floor=None):
    """Score one hypothesis; a bounded score-floor result has no numeric score."""
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
    if score_floor is not None:
        if not association or mode != "robust_ridge":
            raise ValueError("score_floor is only supported for robust_ridge associations")
        if isinstance(score_floor, (bool, np.bool_)):
            raise ValueError("score_floor must be finite")
        try:
            score_floor = float(score_floor)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("score_floor must be finite") from error
        if not np.isfinite(score_floor):
            raise ValueError("score_floor must be finite")
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
    # linspace(..., 2) produces the same trial twice for a fixed clock. Keep
    # one evaluation and report one trial; the fitted clock and score are
    # unchanged, including the first-shift tie rule.
    if len(shifts) > 1 and shifts[0] == shifts[-1]:
        shifts = shifts[:1]
    best = {"score":-np.inf}
    if mode == "robust_ridge":
        best["score_kind"] = ("matched_group_support_minus_normalized_residual" if association
                              else "negative_robust_ridge_loss_hz")
    assessment = {"complete": False, "evaluated_trials": 0, "rejected_trials": 0,
                  "unknown_trials": 0, "reasons": [], "scheduled_trials": len(shifts),
                  "trial_count_semantics": "disjoint_evaluated_rejected_unknown",
                  "empty_clock_domain": len(shifts) == 0}
    reasons = set()
    unknown_bounds = []
    # Every accepted group contributes at most one; a strict comparison keeps ties eligible.
    floor_pruned = bool(score_floor is not None and len(shifts) > 0 and len(events) < score_floor)
    if floor_pruned:
        # A ceiling must not turn malformed fit inputs into a successful assessment.
        from .matching import _frequency_scale, _ridge_fit_inputs
        for event, measurement in zip(events, measurements):
            value = _frequency_scale(event)
            if isinstance(value, (bool, np.bool_)):
                raise ValueError("Frequency loss scales must be finite and positive")
            try:
                scale = float(value)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError("Frequency loss scales must be finite and positive") from error
            if not np.isfinite(scale) or scale <= 0 or not np.isfinite(3*scale):
                raise ValueError("Frequency loss scales must be finite and positive")
            _ridge_fit_inputs(measurement, scale, event.get("quality", {}).get("source_drift_fraction", 0.02))
        best["score"] = None
        assessment["unknown_trials"] = len(shifts)
        reasons.add("matched_group_count_below_score_floor")
    selected_tracks = ([tracks[p["flight_id"]] for p in candidate["passes"]]
                       if mode == "robust_ridge" and not floor_pruned else None)
    batches = None
    if mode == "robust_ridge" and not floor_pruned and len(shifts) > 1:
        from .matching import batch_acoustic_trials
        batches = batch_acoustic_trials(selected_tracks, measurements, observer, anchor + shifts, c)
    for trial, shift in enumerate(() if floor_pruned else shifts):
        if mode == "robust_ridge":
            from .matching import score_ridges
            precomputed = ([None if batch is None else (batch[0][trial], batch[1][trial]) for batch in batches]
                           if batches is not None else None)
            try:
                result = score_ridges(selected_tracks, events, measurements, observer, anchor+shift, c,
                                      acoustic_results=precomputed)
            except AcousticSupportError as error:
                assessment["unknown_trials"] += 1
                reasons.add(str(error))
                unknown_bounds.append(None)
                continue
            if association:
                from .matching import association_score
                result = association_score(result, events)
            classification, reason = _ridge_trial_classification(result, events, association)
            if classification == "unknown":
                assessment["unknown_trials"] += 1
                reasons.add("incomplete_ridge_or_trajectory_support" if reason == "incomplete_acoustic_support" else reason)
                unknown_bounds.append(_association_trial_bound(result, events) if association else None)
            elif classification == "rejected":
                assessment["rejected_trials"] += 1
                reasons.add("acoustic_loss_exceeds_limit")
            else:
                assessment["evaluated_trials"] += 1
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
    if mode == "robust_ridge":
        if not len(shifts):
            reasons.add("no_clock_trials")
        assessment["complete"] = bool(len(shifts) and assessment["unknown_trials"] == 0)
        assessment["reasons"] = sorted(reasons)
        if association and assessment["unknown_trials"]:
            if floor_pruned:
                assessment.update(
                    bounded_unknown_trials=len(shifts),
                    bounded_unknown_rejections=0,
                    unknown_score_upper_bound=float(len(events)),
                    unknown_score_bound_kind="matched_group_support_minus_normalized_residual",
                    unknown_score_bound_method="group_count_ceiling")
            else:
                finite_bounds = [value for value in unknown_bounds if value is not None and np.isfinite(value)]
                assessment.update(
                    bounded_unknown_trials=sum(value is not None for value in unknown_bounds),
                    bounded_unknown_rejections=sum(value == -np.inf for value in unknown_bounds if value is not None),
                    unknown_score_upper_bound=max(finite_bounds) if finite_bounds else None,
                    unknown_score_bound_kind="matched_group_support_minus_normalized_residual",
                    unknown_score_bound_method="nonnegative_loss_and_validated_event_fits")
        best["scoring_assessment"] = assessment
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
