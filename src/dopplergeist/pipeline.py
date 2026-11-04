"""One command from recording + flight data to ranked, plotted locations."""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .audio import measure
from .finite_search import classified_assessment
from .geometry import AcousticSupportError,ecef
from .provenance import RunProvenance,implementation_provenance
from .search import cpa_table,pair_candidates,score_candidate
from .terrain import Terrain,CopernicusTerrain,corridor_grid,refine_grid
from .tracks import load_tracks,unix_time


def dump(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n")


def support_failure(error):
    return {"track_id":error.track_id,"reason":error.reason,
            "emission_intervals_s":error.emission_intervals_s,
            "receive_intervals_s":error.receive_intervals_s}


def score_block(candidates,lookup,track_lookup,events,measurements,parameters,origin,progress=None):
    """Score a block of candidates against one set of events and measurements.

    Module level and side-effect free so a worker process can run it. The scoring loop itself is
    unchanged from the inline version it replaces; only the artifact writing moved to the caller.
    """
    ranked,unknown=[],[]
    reported=dict(evaluated_trials=0,rejected_trials=0,unknown_trials=0)
    unreported=0
    for i,candidate in enumerate(candidates):
        point=lookup[candidate["point_id"]]
        failure=None
        try:
            row=score_candidate(candidate,point,track_lookup,events,measurements,**parameters)
        except AcousticSupportError as error:
            # A legacy scorer can stop before reporting its clock trials.
            # Do not label that interrupted candidate a known rejection.
            failure=support_failure(error)
            row={"score":-np.inf}
        assessment=row.get("scoring_assessment")
        counted=(isinstance(assessment,dict) and all(type(assessment.get(key)) is int
                 and assessment[key]>=0 for key in reported))
        if counted:
            for key in reported:
                reported[key]+=assessment[key]
        else:
            unreported+=1
        known=parameters["mode"]=="robust_ridge" and classified_assessment(row)
        finite=bool(row["score"] is not None and np.isfinite(row["score"]))
        pass_times=[float(p["emission_time"]) for p in candidate["passes"]]
        if not known:
            anchor=(origin if origin is not None else
                    candidate["passes"][0]["receive_time"]-events[0]["cpa_receive_s"])
            lo,hi=anchor-parameters["time_sweep_s"],anchor+parameters["time_sweep_s"]
            if parameters["mode"]=="robust_ridge" and "recording_start_bounds_s" in candidate:
                lower,upper=candidate["recording_start_bounds_s"]
                lo,hi=lower-parameters["time_sweep_s"],upper+parameters["time_sweep_s"]
                if origin is not None:
                    lo,hi=max(lo,origin-parameters["time_sweep_s"]),min(hi,origin+parameters["time_sweep_s"])
            unknown.append({"point_id":int(point.point_id),
                "receiver":{key:float(getattr(point,key)) for key in ("x","y","lat","lon","elev_m")},
                "flight_ids":[p["flight_id"] for p in candidate["passes"]],
                "event_indices":list(candidate.get("event_indices",range(len(events)))),
                "pass_emission_times_s":pass_times,"recording_start_domain_s":[float(lo),float(hi)],
                "clock_domain_kind":"scorer_proposal_not_independent_recording_time",
                "clock_settings":parameters,"score_kind":row.get("score_kind"),
                "scoring_assessment":assessment,"failure":failure,
                "finite_best":finite,"finite_score":float(row["score"]) if finite else None,
                "reason":(failure["reason"] if failure else "unclassified_clock_envelope"),
                "coverage_envelope":"whole_candidate_clock_domain_conservative"})
        if finite:
            row["pass_emission_times_s"]=pass_times
            row["core_assessment_complete"]=bool(known)
            ranked.append(row)
        if progress is not None and i and i%100==0:
            progress(i,len(candidates))
    return ranked,unknown,reported,unreported


_WORKER_STATE={}


def _init_worker(state):
    _WORKER_STATE.update(state)


def _score_chunk(chunk):
    state=_WORKER_STATE
    return score_block(chunk,state["lookup"],state["track_lookup"],state["events"],
                       state["measurements"],state["parameters"],state["origin"])


def _validated_scoring_chunk(chunk):
    """Reject invalid chunk sizes before scoring or producing artifacts."""
    if type(chunk) is not int or chunk < 1:
        raise ValueError("scoring_chunk must be a positive integer")
    return chunk


def score_chunks(candidates,chunks,workers,state,progress=None):
    """Score ``candidates`` in ``chunks`` blocks, optionally in worker processes.

    Candidates are scored independently, so splitting them cannot change a score; results are
    concatenated in chunk order, which keeps the ranked list (and therefore tie ordering) identical
    to a serial pass. Workers share the loaded tracks and measurements copy-on-write, which is why
    this uses ``fork`` and falls back to a serial loop where ``fork`` is unavailable.
    """
    chunks=_validated_scoring_chunk(chunks)
    blocks=[candidates[i:i+chunks] for i in range(0,len(candidates),chunks)] or []
    results=[]
    context=None
    if workers>1 and len(blocks)>1:
        import multiprocessing as mp
        if "fork" in mp.get_all_start_methods():
            context=mp.get_context("fork")
    if context is None:
        if progress is None:
            progress=lambda done,total: print(f"Scored {done}/{total} candidates",flush=True)
        for block in blocks:
            results.append(score_block(block,state["lookup"],state["track_lookup"],state["events"],
                                       state["measurements"],state["parameters"],state["origin"],
                                       progress=progress))
        return results
    done=0
    with context.Pool(min(workers,len(blocks)),initializer=_init_worker,initargs=(state,)) as pool:
        for block,result in zip(blocks,pool.imap(_score_chunk,blocks)):
            results.append(result)
            done+=len(block)
            if progress is None:
                print(f"Scored {done}/{len(candidates)} candidates",flush=True)
            else:
                progress(done,len(candidates))
    return results


def merge_blocks(results):
    """Concatenate per-block scoring results in block order."""
    ranked,unknown=[],[]
    reported=dict(evaluated_trials=0,rejected_trials=0,unknown_trials=0)
    unreported=0
    for block_ranked,block_unknown,block_reported,block_unreported in results:
        ranked.extend(block_ranked)
        unknown.extend(block_unknown)
        for key in reported:
            reported[key]+=block_reported[key]
        unreported+=block_unreported
    return ranked,unknown,reported,unreported


def run(config_path,output_dir):
    began=time.monotonic()
    code_root=Path(__file__).resolve().parents[1]
    implementation=implementation_provenance(code_root)
    config_path=Path(config_path).resolve()
    config_bytes=config_path.read_bytes()
    config=json.loads(config_bytes)
    provenance=RunProvenance(config_path,config_bytes)
    provenance.collect_declared_inputs(config)
    output=Path(output_dir).resolve()
    output.mkdir(parents=True,exist_ok=True)
    def local(path):
        p=Path(path)
        return p if p.is_absolute() else config_path.parent/p
    audio=local(config["audio"])
    grid=config.get("grid",{})
    bounds=grid.get("bounds")
    crs=grid.get("crs","EPSG:5070")
    profile=receiver_mask=None
    if "country" in config or "search" in config:
        from .contracts import validate_request
        from .geography import profile_for_search,receiver_mask_for_search
        area=config.get("search",{})
        if not isinstance(area,dict):
            raise ValueError("Research search must be a country/coverage object")
        area=dict(area)
        if "country" in config:
            if "country" in area and area["country"]!=config["country"]:
                raise ValueError("Research country and search.country disagree")
            area["country"]=config["country"]
        if bounds is not None:
            if "bounds_wsen" in area and area["bounds_wsen"]!=bounds:
                raise ValueError("Research grid.bounds and search.bounds_wsen disagree")
            area["bounds_wsen"]=bounds
        area=validate_request({"schema_version":1,"audio_path":str(audio),"search":area})["search"]
        profile=profile_for_search(area)
        if "crs" in grid and grid["crs"]!=profile.crs:
            raise ValueError("Research grid.crs must match the selected country profile")
        bounds=area.get("bounds_wsen",profile.bounds_wsen)
        crs=profile.crs
        receiver_mask=receiver_mask_for_search(area,
            cache_root=local(config.get("cache_root",output/"cache")),offline=config.get("offline",True))
    measurements=[]
    events=[]
    for i,settings in enumerate(config["events"]):
        settings=dict(settings)
        if settings.get("ridge_csv"):
            settings["ridge_csv"]=str(local(settings["ridge_csv"]))
        result=measure(audio,settings,output/f"event-{i+1}")
        fit=result[-1]
        print("Event",i+1,json.dumps(fit),flush=True)
        if not fit["detected"] and not settings.get("ridge_csv"):
            raise ValueError(f"Event {i+1} lacks a supported Doppler detection; inspect its spectrogram")
        settings.setdefault("cpa_receive_s",fit["cpa_receive_s"])
        settings.setdefault("speed_range_mps",[max(10,fit["speed_mps"]*0.75),min(260,fit["speed_mps"]*1.25)])
        settings.setdefault("slant_range_m",[max(50,fit["slant_m"]*0.6),fit["slant_m"]*1.5])
        settings.setdefault("f0_range_hz",[fit["f0_hz"]-max(3,fit["f0_hz"]*0.02),fit["f0_hz"]+max(3,fit["f0_hz"]*0.02)])
        measurements.append(result)
        events.append(settings)
    if any(events[i]["cpa_receive_s"]>=events[i+1]["cpa_receive_s"] for i in range(len(events)-1)):
        raise ValueError("Events must be in chronological recording order")
    tracks=[]
    imports=[]
    origin=unix_time(config["recording_start_utc"]) if config.get("recording_start_utc") is not None else None
    track_bounds=None
    if bounds:
        # Preserve enough pre/post-event trajectory to model the entire audible
        # window, not just positions lying within the observer search rectangle.
        margin=max(e["slant_range_m"][1]+(e["end_s"]-e["start_s"])*e["speed_range_mps"][1] for e in events)/70000+0.1
        track_bounds=[bounds[0]-margin,bounds[1]-margin,bounds[2]+margin,bounds[3]+margin]
    time_range=None if origin is None else [origin+events[0]["start_s"]-120,origin+events[-1]["end_s"]+120]
    for path in config["tracks"]:
        path=local(path)
        imported,report=load_tracks(path,max_gap_s=config.get("max_track_gap_s",30),
                                   type_database=local(config["type_database"]) if config.get("type_database") else None,
                                   bounds=track_bounds,time_range=time_range)
        tracks.extend(imported)
        imports.append(dict(report,path=str(path)))
    if len({t.id for t in tracks})!=len(tracks):
        raise ValueError("Flight IDs must identify unique imported trajectory segments")
    if not tracks:
        raise ValueError("No usable flight trajectories")
    ground=config["terrain"]
    geoid=local(ground["geoid_raster"]) if ground.get("geoid_raster") else None
    terrain=(CopernicusTerrain(local(ground["copernicus_cache"]),geoid) if ground.get("copernicus_cache") else
             Terrain([local(p) for p in ground.get("rasters",[])],ground.get("constant_m"),geoid))
    coarse=grid.get("spacing_m",200)
    points=corridor_grid(tracks,events,coarse,terrain,crs,bounds,origin,receiver_mask)
    print(f"Grid: {len(points)} points; {len(tracks)} trajectory segments",flush=True)
    radius=max(event["slant_range_m"][1] for event in events)
    c=config.get("sound_speed_mps",343.0)
    filters=config.get("filters",{})
    support_stages=[]
    support_dir=output/"support"
    support_dir.mkdir(exist_ok=True)
    def support_summary():
        return {"scope":"configured_research_ranking",
            "model_support_complete":all(stage["complete"] for stage in support_stages),
            "model_assessment_complete":all(stage["complete"] for stage in support_stages),
            "unsupported_cpa_track_evaluations":sum(s.get("excluded_track_count",0) for s in support_stages),
            "unknown_candidate_envelopes":sum(s.get("unknown_candidate_count",0) for s in support_stages),
            "unreported_trial_envelopes":sum(s.get("unreported_trial_envelopes",0) for s in support_stages),
            "reported_unknown_trials":sum(s.get("reported_trials",{}).get("unknown_trials",0) for s in support_stages),
            "count_semantics":"work evaluations, including repeated tracks and receivers across stages",
            "stages":support_stages}
    def record_support(stage,detail):
        dump(support_dir/f"{stage}.json",detail)
        support_stages.append({key:value for key,value in detail.items()
                               if key not in ("excluded_tracks","unknown_candidates")}
                              | {"artifact":f"support/{stage}.json"})
        dump(output/"model-support.json",support_summary())
    def select(points,stage):
        tables,excluded=[],[]
        bounds=([float(points.lon.min()),float(points.lat.min()),
                 float(points.lon.max()),float(points.lat.max())] if len(points) else None)
        for track in tracks:
            try:
                table=cpa_table([track],points,radius,c,config.get("cpa_step_s",2))
            except AcousticSupportError as error:
                # Exclude this track's whole stage, not just the reported bad
                # intervals. Missing competing passes remain unassessed.
                excluded.append({"track_id":track.id,"failure":support_failure(error),
                    "emission_time_range_s":[float(track.time[0]),float(track.time[-1])],
                    "receiver_bounds_wsen":bounds,"receiver_point_count":len(points),
                    "coverage_envelope":"whole_track_whole_stage_conservative"})
                continue
            if len(table):
                tables.append(table)
        table=(pd.concat(tables,ignore_index=True) if tables else pd.DataFrame(columns=
               ["point_id","flight_id","emission_time","receive_time","distance_m","speed_mps"]))
        if len(table):
            table=table.sort_values(["point_id","flight_id","emission_time"]).reset_index(drop=True)
        record_support(stage,{"stage":stage,"kind":"cpa","complete":not excluded,
            "receiver_bounds_wsen":bounds,"receiver_point_count":len(points),
            "track_evaluations":len(tracks),"cpa_rows":len(table),
            "excluded_track_count":len(excluded),"excluded_tracks":excluded})
        candidates,counts=pair_candidates(table,events,
            offset_tolerance_s=filters.get("offset_tolerance_s",5),time_origin=origin,
            time_tolerance_s=filters.get("known_time_tolerance_s",5),silence=filters.get("silence"))
        if excluded:
            print(f"{stage}: {len(excluded)} unsupported track evaluations; model coverage is partial",flush=True)
        return candidates,counts
    candidates,counts=select(points,"coarse-cpa")
    dump(output/"filter-counts.json",counts)
    print("Coarse filters:",counts,flush=True)
    points.to_csv(output/"coarse-grid.csv",index=False)
    dump(output/"measured-events.json",events)
    fine=grid.get("scoring_spacing_m",100)
    if candidates and fine<coarse:
        ids={candidate["point_id"] for candidate in candidates}
        points=refine_grid(points[points.point_id.isin(ids)],coarse,fine,terrain,crs,
                           bounds=bounds,receiver_mask=receiver_mask)
        candidates,fine_counts=select(points,"scoring-cpa")
    else:
        fine_counts=counts
    print("Scoring filters:",fine_counts,flush=True)
    dump(output/"scoring-filter-counts.json",fine_counts)
    scoring=config.get("scoring",{})
    parameters=dict(mode=scoring.get("mode","brightness"),time_origin=origin,
        time_sweep_s=scoring.get("time_sweep_s",5),time_step_s=scoring.get("time_step_s",0.5),c=c)
    workers=config.get("scoring_workers",1)
    if type(workers) is not int or workers<1:
        raise ValueError("scoring_workers must be a positive integer")
    chunk=config.get("scoring_chunk")
    if chunk is not None:
        chunk=_validated_scoring_chunk(chunk)
    def rank(candidates,points,stage):
        # Candidates are scored independently, so the pool cannot change a score; the ranked list is
        # assembled in candidate order, which keeps the serial ordering (and its tie handling).
        lookup={row.point_id:row for row in points.itertuples()}
        state=dict(lookup=lookup,track_lookup={track.id:track for track in tracks},events=events,
                   measurements=measurements,parameters=parameters,origin=origin)
        size=chunk or max(64,(len(candidates)+4*workers-1)//(4*workers))
        ranked,unknown,reported,unreported=merge_blocks(
            score_chunks(candidates,size,workers,state))
        record_support(stage,{"stage":stage,"kind":"scoring","complete":not unknown,
            "candidate_envelopes":len(candidates),"finite_candidates":len(ranked),
            "unknown_candidate_count":len(unknown),"unreported_trial_envelopes":unreported,
            "reported_trials":reported,"unknown_candidates":unknown})
        return sorted(ranked,key=lambda row:row["score"],reverse=True)
    ranked=rank(candidates,points,"grid-scoring")
    dump(output/"ranked-grid.json",ranked)
    # Refine the best location from each flight combination rather than spending
    # every refinement slot on neighbouring points of the winning combination.
    best_pairs={}
    for row in ranked:
        best_pairs.setdefault(tuple(row["flight_ids"]),row)
    chosen=list(best_pairs.values())[:grid.get("refine_pairs",10)]
    final_spacing=grid.get("refine_spacing_m",25)
    if chosen and final_spacing<fine:
        seeds=pd.DataFrame(chosen)
        points2=refine_grid(seeds,fine,final_spacing,terrain,crs,bounds=bounds,receiver_mask=receiver_mask)
        candidates2,refined_counts=select(points2,"refinement-cpa")
        ranked2=rank(candidates2,points2,"refinement-scoring")
        ranked=sorted(ranked+ranked2,key=lambda r:r["score"],reverse=True)
        dump(output/"refinement-filter-counts.json",refined_counts)
    best_pairs={}
    for row in ranked:
        best_pairs.setdefault(tuple(row["flight_ids"]),row)
    dump(output/"ranked.json",ranked)
    dump(output/"flight-combinations.json",list(best_pairs.values()))
    provenance.collect_terrain_inputs(ground,terrain)
    report={"config":config,"measured_events":events,"imports":imports,"sources":provenance.sources,
            "implementation_sha256":implementation["sha256"],
            "implementation_sources":implementation["sources"],"provenance":provenance.declaration(),
            "coarse_filter_counts":counts,"scoring_filter_counts":fine_counts,
            "ranked_points":len(ranked),"flight_combinations":len(best_pairs),"best":ranked[0] if ranked else None,
            "result_scope":"configured_research_ranking","accepted_location":False,
            "model_support_complete":support_summary()["model_support_complete"],
            "model_assessment_complete":support_summary()["model_assessment_complete"],
            "model_support":support_summary(),
            "limitations":["Configured event windows and receiver bounds do not establish independent automatic localization.",
                "Source flight coverage and competing locations are not certified by this research ranking.",
                "Excluded trajectories and unknown clock envelopes remain unassessed, not ruled out.",
                "Legacy brightness/ridge scores do not report exhaustive clock-trial assessment."],
            "elapsed_s":time.monotonic()-began,
            "scoring_time_is_locked":True}
    if profile is not None:
        report["search_geography"]={"country":profile.country,"coverage":profile.coverage,
            "bounds_wsen":list(bounds),"crs":crs}
        if receiver_mask is not None:
            report["search_geography"]["receiver_mask"]=receiver_mask.identity
    dump(output/"report.json",report)
    if ranked:
        plot_results(output,ranked,tracks,measurements,c)
        print("Best:",json.dumps(ranked[0]),flush=True)
    else:
        print("No supported hypothesis; inspect model-support.json and filter counts",flush=True)
    return report


def plot_results(output,ranked,tracks,measurements,c=343.0):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    selected=[r for r in ranked if r["flight_ids"]==ranked[0]["flight_ids"]]
    fig,ax=plt.subplots(figsize=(7,6),layout="constrained")
    im=ax.scatter([r["lon"] for r in selected],[r["lat"] for r in selected],
                  c=[r["score"] for r in selected],s=12,cmap="viridis")
    ax.scatter(ranked[0]["lon"],ranked[0]["lat"],marker="*",s=120,color="red",label="Highest score")
    ax.set(xlabel="Longitude",ylabel="Latitude",title="Location scores for the best flight combination")
    ax.legend()
    fig.colorbar(im,ax=ax,label="Score (higher is better)")
    fig.savefig(output/"location-scores.png",dpi=160)
    plt.close(fig)
    lookup={t.id:t for t in tracks}
    from .matching import predict_fitted_ridge
    for i,(spec,ridge,weight,fit) in enumerate(measurements):
        best=ranked[0]
        track=lookup[best["flight_ids"][i]]
        diagnostics=dict(best.get("event_diagnostics", [{} for _ in measurements])[i],f0_hz=best["f0_hz"][i])
        predicted=predict_fitted_ridge(track,ecef(best["lat"],best["lon"],best["elev_m"]),
            best["recording_start_time_s"]+spec.time,diagnostics,c)
        fig,ax=plt.subplots(figsize=(10,4),layout="constrained")
        ax.pcolormesh(spec.time,spec.frequency,spec.contrast,shading="auto",cmap="magma",vmin=0,vmax=6)
        ax.plot(spec.time,predicted,color="cyan",lw=1.1,label="Best physical model")
        ax.set(xlabel="Recording time (s)",ylabel="Frequency (Hz)",title=f"Event {i+1}: shared clock, {track.id}")
        ax.legend(loc="upper right")
        fig.savefig(output/f"event-{i+1}-best-model.png",dpi=160)
        plt.close(fig)
