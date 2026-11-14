"""Bounded reconciliation of measured tonal tracks; no physical-source inference.

All time differences below are seconds. Pairwise constant-scale fits have one
parameter; group-wide reconciliation prevents weak transitive bridges.
"""
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
import hashlib
import heapq
from bisect import bisect_right
from math import sqrt
from statistics import median

import numpy as np
from scipy import ndimage
from scipy.optimize import isotonic_regression


class DiscoveryError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass
class Ridge:
    points: np.ndarray
    origins: tuple


def identifier(prefix, points, source=""):
    # IDs depend on observations, not input enumeration or proposal count.
    values = np.ascontiguousarray(points[:, :3], dtype="<f8")
    return prefix + hashlib.sha256(source.encode() + values.tobytes()).hexdigest()[:20]


def key(ridge):
    p = ridge.points
    return (float(p[0, 0]), float(np.median(p[:, 1])), identifier("", p))


def intervals(times, hop):
    """Union of observed cells; scalar or per-observation hop widths."""
    widths=np.full(len(times),hop) if np.ndim(hop)==0 else np.asarray(hop)
    result=[]
    for t,width in sorted(zip(times,widths)):
        left,right=max(0.,float(t-width/2)),float(t+width/2)
        if result and left<=result[-1][1]+1e-8:result[-1][1]=max(result[-1][1],right)
        else:result.append([left,right])
    return result


def support(points, settings):
    hops=points[:,6] if points.shape[1]>6 else settings.hop_s
    windows=points[:,7] if points.shape[1]>7 else np.full(len(points),settings.window_s)
    cells=intervals(points[:,0],hops)
    observed=sum(b-a for a,b in cells)
    if np.ptp(windows)<1e-9:
        independent=observed/float(windows[0])
    else:
        # Integrate the maximum available temporal information rate. Overlapping
        # profiles never add their correlated observations twice.
        widths=np.full(len(points),hops) if np.ndim(hops)==0 else hops
        events=[]
        for i,(t,h,w) in enumerate(zip(points[:,0],widths,windows)):
            events.extend([(max(0.,float(t-h/2)),1,i,1/float(w)),(float(t+h/2),-1,i,1/float(w))])
        active=set();heap=[];last=events[0][0] if events else 0.;independent=0.
        for time,kind,i,density in sorted(events):
            while heap and heap[0][1] not in active:heapq.heappop(heap)
            if heap:independent+=(time-last)*(-heap[0][0])
            if kind==1:active.add(i);heapq.heappush(heap,(-density,i))
            else:active.discard(i)
            last=time
    return cells,float(observed),float(independent)


def uncertainty(points, settings):
    f = points[:, 1]
    smooth = ndimage.median_filter(f, size=min(5, len(f) // 2 * 2 + 1), mode="nearest")
    return float(max(np.median(points[:,4]) if points.shape[1]>4 else 1/settings.window_s, 1.4826*np.median(np.abs(f-smooth))))


def aligned(a, b, settings):
    # Use measured times and interpolate only within a supported observation gap.
    first, last = max(a[0, 0], b[0, 0]), min(a[-1, 0], b[-1, 0])
    times = a[(a[:, 0] >= first) & (a[:, 0] <= last), 0]
    if len(times) < 3:
        return None
    following = np.clip(np.searchsorted(b[:, 0], times), 0, len(b) - 1)
    previous = np.maximum(0, following - 1)
    exact = np.abs(b[following, 0] - times) < 1e-7
    supported = exact | ((b[following, 0] - b[previous, 0] <= settings.max_gap_s)
                         & (times >= b[previous, 0]))
    times = times[supported]
    if len(times) < 3:
        return None
    return times, np.interp(times, a[:, 0], a[:, 1]), np.interp(times, b[:, 0], b[:, 1])


def prediction_model(points, settings):
    """Sufficient local evidence for repeated endpoint predictions (Hz, seconds)."""
    tail=points[-8:];last=tail[-1]
    resolution=1/float(last[7]) if len(last)>7 else 1/settings.window_s
    measured_sigma=float(last[4]) if len(last)>4 else resolution
    if len(tail)==1:
        return float(last[0]),float(last[1]),measured_sigma,0.,0.,0.,max(8.,float(last[1])*.08)
    rates=[(float(b[1])-float(a[1]))/(float(b[0])-float(a[0])) for a,b in zip(tail,tail[1:])]
    rate=median(rates)
    dispersion=1.4826*median(abs(v-rate) for v in rates)
    scatter=1.4826*median(abs(float(p[1])-float(last[1])-rate*(float(p[0])-float(last[0]))) for p in tail)
    quality=max(1.,min(12.,float(last[2])))
    sigma=measured_sigma*sqrt(1+settings.min_contrast/quality)
    span=max(float(last[6]) if len(last)>6 else settings.hop_s,float(last[0]-tail[0][0]))
    rate_uncertainty=sqrt(dispersion**2+2*sigma**2/span**2)
    return float(last[0]),float(last[1]),sigma,rate,scatter,rate_uncertainty,measured_sigma


def predict(model,time,next_sigma=None):
    last_time,frequency,sigma,rate,scatter,rate_uncertainty,measurement=model
    dt=float(time-last_time)
    if next_sigma is None:next_sigma=measurement if rate_uncertainty else sigma
    tolerance=measurement*dt if not rate_uncertainty else 3*sqrt(sigma**2+float(next_sigma)**2+scatter**2+(dt*rate_uncertainty)**2)
    return frequency+rate*dt,float(tolerance)


def forecast(points, time, settings, next_sigma=None):
    """History/measurement uncertainty grows with actual elapsed seconds.

    Linking, continuity and fragment scoring share this predictor. Short or
    noisy histories carry slope uncertainty; no unit-time displacement is used.
    """
    return predict(prediction_model(points,settings),time,next_sigma)


def overlap_duration(a,b):
    i=j=0;total=0.
    while i<len(a) and j<len(b):
        total+=max(0.,min(a[i][1],b[j][1])-max(a[i][0],b[j][0]))
        if a[i][1]<b[j][1]:i+=1
        else:j+=1
    return total


def shape_consistency(points,settings):
    """Assess one monotone leg or one resolved turn against measurement error.

    PAVA is linear in observed samples. Only eight candidate turn positions
    are tried; fitting noise with arbitrary turns is not allowed.
    """
    t,f=points[:,:2].T
    sigma=points[:,4] if points.shape[1]>4 else np.full(len(f),1/settings.window_s)
    weights=1/np.maximum(sigma,1e-6)**2
    candidates=[]
    for increasing in (True,False):
        fit=isotonic_regression(f,weights=weights,increasing=increasing).x
        candidates.append((float(np.mean(((f-fit)/sigma)**2)),fit,'rising' if increasing else 'falling'))
    for split in np.unique(np.linspace(2,len(f)-3,8,dtype=int)):
        if split<2 or split>=len(f)-2:continue
        if min(t[split]-t[0],t[-1]-t[split])<max(settings.window_s,1.):continue
        if min(np.ptp(f[:split+1]),np.ptp(f[split:]))<3*float(np.median(sigma)):continue
        for rising in (True,False):
            first=isotonic_regression(f[:split+1],weights=weights[:split+1],increasing=rising).x
            last=isotonic_regression(f[split+1:],weights=weights[split+1:],increasing=not rising).x
            fit=np.r_[first,last]
            candidates.append((float(np.mean(((f-fit)/sigma)**2))+.25,fit,'turning'))
    loss,fit,direction=min(candidates,key=lambda x:x[0])
    return float(np.quantile(np.abs(f-fit)/sigma,.9)),direction


def distributed_motion(points,settings,excursion):
    """Resolved changes across four elapsed-time regions, not frame jitter.

    A step between two stationary tones moves only one of three regional
    transitions. At least two must exceed independent-window uncertainty.
    Missing observations do not acquire support by spanning a region.
    """
    t=points[:,0];edges=np.linspace(t[0],t[-1]+1e-8,5);regions=[]
    for first,last in zip(edges,edges[1:]):
        p=points[(t>=first)&(t<last)]
        if len(p)<2:
            regions.append(None);continue
        _,observed,independent=support(p,settings)
        if observed<.35*(last-first):regions.append(None);continue
        sigma=uncertainty(p,settings)/sqrt(max(1.,independent))
        regions.append((float(np.median(p[:,1])),sigma))
    resolved=0
    for a,b in zip(regions,regions[1:]):
        if a is not None and b is not None and abs(a[0]-b[0])>=max(1.5*sqrt(a[1]**2+b[1]**2),.1*excursion):resolved+=1
    return resolved/3


def motion(points, settings):
    """Evidence and explicit rejection thresholds, independent of duration gate."""
    t, f, w = points[:, :3].T
    cells, observed, independent = support(points,settings)
    span = cells[-1][1]-cells[0][0]
    sigma = uncertainty(points, settings)
    smooth = ndimage.median_filter(f, size=5, mode="nearest")
    dt = np.diff(t)
    # Missing intervals do not contribute to moving fraction or smoothness.
    valid = dt <= settings.max_gap_s
    slopes = np.diff(smooth) / dt
    excursion = float(np.quantile(smooth, .95) - np.quantile(smooth, .05))
    required = max(settings.min_drop_hz, float(np.median(f)) * settings.min_fractional_drop, 4 * sigma)
    moving = valid & (np.abs(slopes) > max(.05, excursion / max(span, 1) * .2))
    hops=points[:,6] if points.shape[1]>6 else np.full(len(points),settings.hop_s)
    observed_steps=np.minimum(dt,np.minimum(hops[:-1],hops[1:]))
    moving_fraction=float(np.sum(observed_steps[moving])/max(np.sum(observed_steps[valid]),float(np.min(hops))))
    # Local prediction on actual timestamps, with uncertainty in Hz and slope.
    errors = []
    for i in range(2, len(t)):
        if dt[i - 1] > settings.max_gap_s:
            continue
        predicted, tolerance = forecast(points[:i], t[i], settings, next_sigma=float(points[i,4]) if points.shape[1]>4 else None)
        errors.append(abs(f[i]-predicted)/tolerance)
    discontinuity = float(np.quantile(errors, .95)) if errors else 0.0
    signs = np.sign(slopes[moving])
    # A turn requires a sustained resolved leg; repeated reversals are modulation
    # or unresolved wandering, not a compulsory descending-flight template.
    runs = []
    for sign, duration, is_observed, displacement in zip(np.sign(slopes), observed_steps, valid, np.diff(smooth)):
        if not is_observed or abs(sign) == 0:
            continue
        if runs and runs[-1][0] == sign:
            runs[-1][1] += duration
            runs[-1][2] += abs(displacement)
        else:
            runs.append([sign, duration, abs(displacement)])
    sustained = [sign for sign, duration, displacement in runs
                 if duration >= max(1.5, observed * .08) and displacement >= max(2*sigma, .15*excursion)]
    turns = sum(a != b for a, b in zip(sustained, sustained[1:]))
    total_variation = float(np.sum(np.abs(np.diff(smooth))[valid]))
    variation_ratio = total_variation / max(excursion, sigma)
    direction = "stationary"
    if len(signs):
        direction = "turning" if turns else ("rising" if np.median(signs) > 0 else "falling")
    metrics = dict(observed_duration_s=float(observed), independent_windows=independent, span_s=float(span), support_fraction=float(observed / span),
                   frequency_excursion_hz=excursion, required_excursion_hz=float(required),
                   frequency_uncertainty_hz=sigma, moving_fraction=moving_fraction,
                   prediction_error_q95=discontinuity, sustained_turns=int(turns),
                   variation_ratio=float(variation_ratio), median_contrast=float(np.median(w)), direction=direction)
    distributed=distributed_motion(points,settings,excursion)
    metrics["resolved_regional_motion_fraction"]=distributed
    shape_residual,shape_direction=shape_consistency(points,settings)
    metrics.update(shape_residual_q90=shape_residual,shape_direction=shape_direction)
    checks = [(excursion >= required, "unresolved_frequency_motion", excursion, required, ">="),
              (moving_fraction >= .35, "insufficient_distributed_motion", moving_fraction, .35, ">="),
              (distributed>=2/3,"motion_concentrated_or_unresolved",distributed,2/3,">="),
              (discontinuity <= 1, "discontinuous_motion", discontinuity, 1, "<="),
              (shape_residual<=2.,"incoherent_frequency_shape",shape_residual,2.,"<="),
              (turns <= 1, "repeated_modulation", turns, 1, "<="),
              (variation_ratio <= 2.8, "wandering_or_modulation", variation_ratio, 2.8, "<=")]
    if points.shape[1]>5:
        prominence=float(np.median(points[:,5]))
        tonal_support=float(np.mean(points[:,5]>=3.))
        metrics.update(median_spectral_prominence_db=prominence,tonal_support_fraction=tonal_support)
        checks.extend([(prominence>=4.,'weak_tonal_concentration',prominence,4.,'>='),
                       (tonal_support>=.6,'insufficient_tonal_support',tonal_support,.6,'>=')])
    reasons = [dict(reason=name, measured=float(value), threshold=float(limit), comparison=op)
               for passed, name, value, limit, op in checks if not passed]
    return metrics, reasons


class Associations:
    def __init__(self, settings):
        self.limit = settings.max_associations
        self.count = 0
        self.decisions = []
        self.decision_counts = Counter()
        self.trace_limit = settings.max_diagnostic_traces
        self.refits = 0
        self.refit_limit = settings.max_joint_refits

    def charge(self):
        self.count += 1
        if self.count > self.limit:
            raise DiscoveryError("association_budget_exceeded", f"Association work exceeded {self.limit} pairs")

    def refit(self):
        self.refits += 1
        if self.refits > self.refit_limit:
            raise DiscoveryError("joint_refit_budget_exceeded",f"Joint refits exceeded {self.refit_limit}")

    def record(self, kind, left, right, **evidence):
        self.decision_counts[kind] += 1
        if len(self.decisions) < self.trace_limit:
            self.decisions.append(dict(kind=kind, left=list(left.origins), right=list(right.origins), **evidence))


def combine(a, b):
    points = np.concatenate((a.points, b.points))
    # Deterministic tie break, strongest contrast per timestamp; no invented data.
    points = points[np.lexsort((points[:, 1], -points[:, 2], points[:, 0]))]
    _, keep = np.unique(points[:, 0], return_index=True)
    return Ridge(points[np.sort(keep)], tuple(sorted(set(a.origins + b.origins))))


def consistent_interleaving(a,b,settings):
    """Shared peaks cannot license contradictory measurements inside gaps."""
    for first,second in ((a,b),(b,a)):
        ix=np.searchsorted(second[:,0],first[:,0])
        inside=(ix>0)&(ix<len(second))
        rows=np.flatnonzero(inside)
        if not len(rows):continue
        right=ix[rows];left=right-1
        exact=np.abs(second[right,0]-first[rows,0])<1e-7
        rows=rows[~exact];right=right[~exact];left=left[~exact]
        if not len(rows):continue
        gaps=second[right,0]-second[left,0]
        if np.any(gaps>settings.max_gap_s):return False
        predicted=np.interp(first[rows,0],second[:,0],second[:,1])
        sigma_a=first[rows,4] if first.shape[1]>4 else 1/settings.window_s
        sigma_l=second[left,4] if second.shape[1]>4 else 1/settings.window_s
        sigma_r=second[right,4] if second.shape[1]>4 else 1/settings.window_s
        tolerance=3*np.sqrt(sigma_a**2+sigma_l**2+sigma_r**2)
        if np.any(np.abs(first[rows,1]-predicted)>tolerance):return False
    return True


def deduplicate(ridges, settings, work):
    """Reconcile reused peaks via a sparse active observation index.

    Four identical measured peaks are necessary, so unrelated overlapping tracks
    need not be compared. Conflicting shared-time observations remain alternatives.
    """
    result=[];ends=[];index=defaultdict(set);membership={};live=set()
    def peaks(points):
        return {(round(float(t),7),round(float(f),6)) for t,f in points[:,:2]}
    def register(i):
        membership[i]=peaks(result[i].points)
        for peak in membership[i]:index[peak].add(i)
        live.add(i);heapq.heappush(ends,(float(result[i].points[-1,0]),i))
    def unregister(i):
        for peak in membership.pop(i,()):
            index[peak].discard(i)
            if not index[peak]:del index[peak]
        live.discard(i)
    for ridge in sorted(ridges,key=key):
        first=float(ridge.points[0,0])
        while ends and ends[0][0]<first:
            end,i=heapq.heappop(ends)
            if i in live and end==result[i].points[-1,0]:unregister(i)
        candidates=Counter(i for peak in peaks(ridge.points) for i in index.get(peak,()))
        combined=False
        for i in sorted(i for i,count in candidates.items() if count>=4):
            previous=result[i]
            work.charge()
            common,li,ri=np.intersect1d(ridge.points[:,0],previous.points[:,0],return_indices=True)
            differences=np.abs(ridge.points[li,1]-previous.points[ri,1])
            if ridge.points.shape[1]>7 and previous.points.shape[1]>7:
                limits=.6*np.maximum(1/ridge.points[li,7],1/previous.points[ri,7])
            else:limits=np.full(len(common),.6/settings.window_s)
            if np.sum(differences<=1e-6)<4 or np.any(differences>limits):continue
            if not consistent_interleaving(ridge.points,previous.points,settings):
                work.record('duplicate_unresolved_interleaving',ridge,previous,reason='conflicting_or_unsupported_gap_observations')
                continue
            work.record('duplicate_measurement',ridge,previous,residual_max_hz=float(np.max(differences)),
                        threshold_hz=float(np.max(limits)),shared_samples=len(common))
            unregister(i);result[i]=combine(previous,ridge);register(i)
            combined=True
            break
        if not combined:
            result.append(ridge);register(len(result)-1)
    return sorted(result,key=key)


def stitch(ridges, settings, work):
    """Score sparse continuations, then reconsider compatible chain links twice.

    Edges are proposals until the joined observations pass continuity. Joint
    fits are cached by member set; an unchanged rejected fit is never retried.
    Adjacent observations can be a continuation, not only large missing gaps.
    """
    ridges = sorted(ridges, key=key)
    starts = [r.points[0,0] for r in ridges]
    edges = []
    def reversed_points(p):
        q=p[::-1].copy();q[:,0]=p[-1,0]-q[:,0];return q
    feature_cache={}
    def features(ridge):
        ids=ridge.origins
        if ids not in feature_cache:
            points=ridge.points;rev=reversed_points(points)
            cells,observed,_=support(points,settings)
            feature_cache[ids]=(prediction_model(points,settings),prediction_model(rev,settings),cells,observed)
        return feature_cache[ids]
    def link_score(left,right):
        a,b=left.points,right.points
        gap=float(b[0,0]-a[-1,0])
        if not 0<gap<=settings.max_fragment_gap_s:return None
        forward,_,cells_a,observed_a=features(left)
        _,backward,cells_b,observed_b=features(right)
        predicted,tolerance=predict(forward,b[0,0])
        back,back_tolerance=predict(backward,backward[0]+gap)
        forward_error=abs(b[0,1]-predicted)/tolerance
        backward_error=abs(a[-1,1]-back)/back_tolerance
        if max(forward_error,backward_error)>3.:return None
        observed_support=observed_a+observed_b-overlap_duration(cells_a,cells_b)
        gap_fraction=gap/(observed_support+gap)
        cost=float(np.sqrt((forward_error**2+backward_error**2)/2)+gap_fraction+(1. if gap_fraction>1-settings.min_support else 0.))
        return cost if cost<=2. else None
    # Keep at most eight scored continuations per endpoint. The runner-up is
    # retained for ambiguity checks; dense neighbourhoods do not trigger all
    # possible joint refits. Pruned links remain unexplored alternatives.
    neighbours=8
    for i,left in enumerate(ridges):
        a=left.points
        first=bisect_right(starts,float(a[-1,0]))
        last=bisect_right(starts,float(a[-1,0]+settings.max_fragment_gap_s))
        forward=features(left)[0];left_sigma=uncertainty(a,settings)
        nearby=[]
        for j in range(first,last):
            b=ridges[j].points;gap=b[0,0]-a[-1,0]
            if abs(b[0,1]-a[-1,1])>max(8.,.08*a[-1,1])*gap+3*left_sigma:continue
            predicted,tolerance=predict(forward,b[0,0])
            if abs(b[0,1]-predicted)>3*tolerance:continue
            nearby.append((abs(b[0,1]-predicted)/tolerance,j))
        nearby.sort()
        work.decision_counts['stitch_cheap_neighbours']+=len(nearby)
        work.decision_counts['stitch_neighbours_pruned']+=max(0,len(nearby)-2*neighbours)
        scored=[]
        for _,j in nearby[:2*neighbours]:
            work.charge()
            score=link_score(left,ridges[j])
            if score is not None:scored.append((score,i,j))
        scored.sort()
        work.decision_counts['stitch_neighbours_pruned']+=max(0,len(scored)-neighbours)
        edges.extend(scored[:neighbours])
    edges.sort()
    incoming=Counter();bounded=[]
    for edge in edges:
        if incoming[edge[2]]<neighbours:
            incoming[edge[2]]+=1;bounded.append(edge)
        else:work.decision_counts['stitch_incoming_pruned']+=1
    edges=bounded
    by_out,by_in={},{}
    for score,i,j in edges:
        by_out.setdefault(i,[]).append((i,j))
        by_in.setdefault(j,[]).append((i,j))
    model_cache={}
    chain_cache=OrderedDict()
    cache_bytes=0
    cache_limit=32*1024**2
    def chain(ids):
        nonlocal cache_bytes
        if len(ids)==1:return ridges[ids[0]]
        if ids in chain_cache:
            chain_cache.move_to_end(ids)
            return chain_cache[ids]
        joined=ridges[ids[0]]
        for member in ids[1:]:joined=combine(joined,ridges[member])
        size=joined.points.nbytes+1024
        if size<=cache_limit:
            while cache_bytes+size>cache_limit:
                _,removed=chain_cache.popitem(last=False)
                cache_bytes-=removed.points.nbytes+1024
            chain_cache[ids]=joined
            cache_bytes+=size
            work.decision_counts['peak_stitch_cache_bytes']=max(work.decision_counts['peak_stitch_cache_bytes'],cache_bytes)
        return joined
    score_cache={}
    def score_ids(a,b):
        cache_key=(a,b)
        if cache_key not in score_cache:
            work.charge()
            score_cache[cache_key]=link_score(chain(a),chain(b))
        return score_cache[cache_key]
    previous=set()
    contexts={i:((i,),(i,)) for i in range(len(ridges))}
    # Each sweep starts from the original fragments. Thus a selected edge can
    # be retracted, rather than becoming irreversible evidence for the next.
    for attempt in range(2):
        ranked=[]
        for initial,i,j in edges:
            score=score_ids(contexts[i][0],contexts[j][1])
            if score is not None:ranked.append((score,i,j))
        ranked.sort()
        costs={(i,j):score for score,i,j in ranked}
        owners={i:(i,) for i in range(len(ridges))}
        chosen=set()
        for score,i,j in ranked:
            left_id,right_id=owners[i],owners[j]
            if score>1. or left_id==right_id or left_id[-1]!=i or right_id[0]!=j:
                continue
            competitors=[]
            for oi,oj in set(by_out.get(i,[])+by_in.get(j,[]))-{(i,j)}:
                a_id,b_id=owners[oi],owners[oj]
                if a_id!=b_id and a_id[-1]==oi and b_id[0]==oj and (oi,oj) in costs:
                    competitors.append(costs[oi,oj])
            if competitors and min(competitors)-score<.1:
                if attempt==1:
                    work.record('ambiguous_continuation',ridges[i],ridges[j],score=score,alternative_score=float(min(competitors)))
                continue
            joined_id=left_id+right_id
            if len(joined_id)>settings.max_stitch_fragments:
                work.record('stitch_fragment_limit',ridges[i],ridges[j],limit=settings.max_stitch_fragments)
                continue
            if joined_id not in model_cache:
                work.charge()
                work.refit()
                joined=chain(joined_id)
                metrics,reasons=motion(joined.points,settings)
                rejected=[r for r in reasons if r['reason'] in ('discontinuous_motion','wandering_or_modulation','repeated_modulation','incoherent_frequency_shape')]
                if metrics['span_s']>=settings.min_duration_s and metrics['moving_fraction']<.2:
                    rejected.append(dict(reason='stationary_switch',measured=metrics['moving_fraction'],threshold=.2))
                if metrics['span_s']>=settings.brief_min_observed_s and metrics['support_fraction']<settings.min_support:
                    rejected.append(dict(reason='missing_support',measured=metrics['support_fraction'],threshold=settings.min_support))
                model_cache[joined_id]=not rejected
            if not model_cache[joined_id]:continue
            for member in joined_id:owners[member]=joined_id
            chosen.add((i,j))
        for i,j in previous-chosen:
            work.record('stitch_retracted',ridges[i],ridges[j],reason='later_context_changed_link_selection')
        next_contexts={}
        for ids in set(owners.values()):
            for position,member in enumerate(ids):
                next_contexts[member]=(ids[:position+1],ids[position:])
        if attempt and chosen==previous:break
        previous=chosen;contexts=next_contexts
    for i,j in sorted(chosen):
        work.record('stitch',ridges[i],ridges[j],score=float(costs[i,j]),gap_s=float(ridges[j].points[0,0]-ridges[i].points[-1,0]))
    work.decision_counts['stitch_candidate_pairs']+=len(edges)
    work.decision_counts['stitch_score_evaluations']+=len(score_cache)
    work.decision_counts['stitch_joint_refits']+=len(model_cache)
    work.decision_counts['stitch_sweeps']+=attempt+1
    return sorted([chain(ids) for ids in set(owners.values())],key=key)


def recurrent_context(points, context, settings, work):
    """Find repeated, time-regular frequency/envelope shapes in actual context.

    This is a modulation diagnostic, not source identification. At least three
    non-overlapping occurrences are needed; a single turn is insufficient.
    """
    t=points[:,0];duration=float(t[-1]-t[0])
    if duration<=0 or points.shape[1]<4:return None
    sigma=uncertainty(points,settings)
    excursion=float(np.ptp(points[:,1]))
    if excursion<4*sigma:return None
    def vector(p):
        grid=np.linspace(p[0,0],p[-1,0],16)
        right=np.clip(np.searchsorted(p[:,0],grid),0,len(p)-1);left=np.maximum(0,right-1)
        valid=(np.abs(p[right,0]-grid)<1e-7)|(p[right,0]-p[left,0]<=settings.max_gap_s)
        if np.sum(valid)<12:return None
        return np.interp(grid,p[:,0],p[:,1]),np.interp(grid,p[:,0],p[:,3])
    target=vector(points)
    if target is None:return None
    freq,amp=target
    matches=[]
    for ridge in context:
        q=ridge.points
        if len(q)<8 or q.shape[1]<4:continue
        if not(q[-1,0]<t[0] or q[0,0]>t[-1]):continue
        qduration=float(q[-1,0]-q[0,0])
        if not .75*duration<=qduration<=1.33*duration:continue
        if abs(np.median(q[:,1])-np.median(points[:,1]))>max(2*sigma,.15*excursion):continue
        if not .75*excursion<=np.ptp(q[:,1])<=1.33*excursion:continue
        work.charge()
        result=vector(q)
        if result is None:continue
        qf,qa=result
        for mirrored in (False,True):
            f,a=(qf[::-1],qa[::-1]) if mirrored else (qf,qa)
            if np.std(f)==0 or np.corrcoef(freq,f)[0,1]<.9:continue
            if np.quantile(abs(freq-f),.9)>2*(sigma+uncertainty(q,settings)):continue
            constant=max(np.std(amp),np.std(a))<1.5 and abs(np.median(amp)-np.median(a))<3.
            envelope=min(np.std(amp),np.std(a))>=1. and np.corrcoef(amp,a)[0,1]>=.8
            if not(constant or envelope):continue
            matches.append((float(q[0,0]),float(q[-1,0]),mirrored,list(ridge.origins)))
            break
    # Collapse alternative associations/profiles of the same occurrence.
    occurrences=[(float(t[0]),float(t[-1]),False,[])]
    for item in sorted(matches):
        if not any(max(a,item[0])<min(b,item[1]) for a,b,_,_ in occurrences):occurrences.append(item)
    occurrences.sort()
    if len(occurrences)<3:return None
    index=next(i for i,o in enumerate(occurrences) if o[0]==float(t[0]) and o[1]==float(t[-1]))
    for start in range(max(0,index-2),min(index+1,len(occurrences)-2)):
        chosen=occurrences[start:start+3]
        gaps=np.diff([o[0] for o in chosen])
        regularity=float(np.std(gaps)/max(np.mean(gaps),settings.hop_s))
        if regularity<=.15:
            return dict(occurrences=len(occurrences),spacing_s=float(np.mean(gaps)),spacing_cv=regularity,
                        intervals_s=[[o[0],o[1]] for o in chosen],scope='recurrent frequency modulation; physical source unresolved')
    return None


def family(scales, tolerance=.006):
    """Minimum-complexity integer family, bounded to orders 1..12.

    Absence of this secondary model does not prohibit coherent nonharmonic
    episodes, which require stronger envelope evidence instead.
    """
    scales = np.asarray(scales) / min(scales)
    fits = []
    for base in range(1, 13):
        orders = np.rint(scales * base).astype(int)
        if max(orders) <= 12 and np.max(np.abs(scales - orders / base) / scales) <= tolerance:
            fits.append(orders.tolist())
    return min(fits, key=lambda orders: (sum(orders), orders)) if fits else None


def related(a, b, settings):
    shared = aligned(a, b, settings)
    if shared is None or len(shared[0]) < 8:
        return None
    t, f, g = shared
    cells_a,observed_a,_=support(a,settings)
    cells_b,observed_b,_=support(b,settings)
    shared_duration=overlap_duration(cells_a,cells_b)
    if shared_duration<.6*min(observed_a,observed_b):return None
    scale = float(np.exp(np.median(np.log(g / f))))
    sigma = uncertainty(b, settings) + scale * uncertainty(a, settings)
    error = float(np.quantile(np.abs(g - scale * f), .9))
    # Uncertainty cannot license an arbitrary ratio fit to unresolved motion.
    excursion = min(float(np.ptp(f)) * scale, float(np.ptp(g)))
    resolved = excursion >= max(6*sigma,.03*np.median(g))
    threshold = min(2*sigma,.15*excursion)
    if excursion < max(3*sigma,.015*np.median(g)) or error > threshold:
        return None
    var_f,var_g=float(np.var(f)),float(np.var(g))
    corr=float(np.corrcoef(f,g)[0,1]) if var_f>0 and var_g>0 else 0.
    sigma_f,sigma_g=uncertainty(a,settings),uncertainty(b,settings)
    reliability=max(0.,1-sigma_f**2/max(var_f,1e-12))*max(0.,1-sigma_g**2/max(var_g,1e-12))
    correlation_limit=max(.75,.96*np.sqrt(reliability))
    if not np.isfinite(corr) or corr<correlation_limit:
        return None
    harmonic = family([1, scale])
    envelope = None
    if a.shape[1] > 3 and b.shape[1] > 3:
        x, y = np.interp(t, a[:, 0], a[:, 3]), np.interp(t, b[:, 0], b[:, 3])
        if min(np.std(x), np.std(y)) >= 1:
            envelope = float(np.corrcoef(x, y)[0, 1])
    if harmonic is None and (envelope is None or not np.isfinite(envelope) or envelope < .65):
        return None
    # Contradictory measured envelopes block even a convenient integer ratio.
    if envelope is not None and np.isfinite(envelope) and envelope < -.25:
        return None
    return dict(scale=scale, residual_q90_hz=error, threshold_hz=float(threshold), evidence_strength="resolved_motion" if resolved else "partial_motion",
                frequency_correlation=corr, correlation_limit=float(correlation_limit), envelope_correlation=envelope,
                shared_observations=int(len(t)), shared_observed_s=float(shared_duration), integer_orders=harmonic)


def reconcile(ridges, settings, work, accept_merge=None):
    """Reconcile strong connections under one group-wide scale model.

    Every member of a group of >=3 needs two resolved-motion witnesses. Every
    overlapping pair is checked against the joint fit, even when its own span
    is too short to establish motion. This permits partial harmonic support
    without permitting a chain of single weak bridges.
    """
    ridges = sorted(ridges, key=key)
    edges = {}
    for i, a in enumerate(ridges):
        for j in range(i + 1, len(ridges)):
            b = ridges[j]
            if b.points[0, 0] > a.points[-1, 0]:
                break
            work.charge()
            evidence = related(a.points, b.points, settings)
            if evidence:
                edges[i, j] = evidence
    fit_cache = {}
    def fit(indices):
        key = tuple(indices)
        if key in fit_cache:
            return fit_cache[key]
        result = fit_uncached(indices)
        fit_cache[key] = result
        return result
    def fit_uncached(indices):
        work.charge()
        work.refit()
        if len(indices) > settings.max_episode_components:
            return None
        positions = {x:i for i,x in enumerate(indices)}
        internal = []
        for ix,x in enumerate(indices):
            for y in indices[ix+1:]:
                work.charge()
                if (x,y) in edges:
                    internal.append((x,y,edges[x,y]))
        if len(indices)>2 and any(sum(x==i or y==i for x,y,_ in internal)<2 for i in indices):
            return None
        matrix, values = [], []
        for x,y,e in internal:
            row = np.zeros(len(indices))
            row[positions[y]], row[positions[x]] = 1., -1.
            matrix.append(row[1:]); values.append(np.log(e["scale"]))
        scales = np.exp(np.r_[0., np.linalg.lstsq(np.asarray(matrix),values,rcond=None)[0]])
        checked_pairs, worst_residual = 0, 0.0
        for ix,x in enumerate(indices):
            for iy in range(ix+1,len(indices)):
                y = indices[iy]
                work.charge()
                shared = aligned(ridges[x].points,ridges[y].points,settings)
                if shared is None:
                    continue
                ratio = scales[iy]/scales[ix]
                error = float(np.quantile(np.abs(shared[2]-ratio*shared[1]),.9))
                sigma = uncertainty(ridges[y].points,settings)+ratio*uncertainty(ridges[x].points,settings)
                checked_pairs += 1
                worst_residual = max(worst_residual,error/(2*sigma))
                if error > 2*sigma:
                    return None
        return dict(scales=scales.tolist(), checked_overlap_pairs=checked_pairs,
                    worst_residual_fraction_of_limit=float(worst_residual),
                    min_resolved_motion_witnesses=min(sum(x==i or y==i for x,y,_ in internal) for i in indices))
    groups = [{i} for i in range(len(ridges))]
    owners = {i:g for g in groups for i in g}
    fitted = {frozenset(g):dict(scales=[1.],checked_overlap_pairs=0,worst_residual_fraction_of_limit=None,
                                      min_resolved_motion_witnesses=0) for g in groups}
    ordered = sorted(edges.items(),key=lambda item:(item[1]["residual_q90_hz"]/item[1]["threshold_hz"],item[0]))
    for attempt in range(2):
        changed = False
        for (i,j),evidence in ordered:
            left, right = owners[i], owners[j]
            if left is right:
                continue
            scales = fit(sorted(left|right))
            if scales is None:
                continue
            if accept_merge is not None and not accept_merge(
                [ridges[x] for x in sorted(left)],fitted[frozenset(left)],
                [ridges[x] for x in sorted(right)],fitted[frozenset(right)],
                [ridges[x] for x in sorted(left|right)],scales):
                work.record('rejected_episode_extension',ridges[i],ridges[j],
                            reason='joint_acceptance_would_invalidate_supported_parent',**evidence)
                continue
            work.record("joint_episode",ridges[i],ridges[j],**evidence)
            left.update(right)
            for member in right:
                owners[member] = left
            groups.remove(right)
            fitted[frozenset(left)] = scales
            changed = True
        if not changed:
            break
    work.decision_counts["episode_joint_refits"] += len(fit_cache)
    for (i,j),evidence in ordered:
        if owners[i] is not owners[j]:
            work.record("unresolved_episode_relation",ridges[i],ridges[j],
                        reason="insufficient_joint_witnesses_or_inconsistent_group_fit",**evidence)
    result = []
    for group in groups:
        indices = sorted(group)
        model = fitted[frozenset(group)]
        scales = model["scales"]
        result.append(([ridges[x] for x in indices],scales,family(scales),model))
    return result
