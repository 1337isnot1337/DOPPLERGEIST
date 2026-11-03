"""One command from recording + flight data to ranked, plotted locations."""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .audio import measure
from .geometry import ecef
from .provenance import RunProvenance,implementation_provenance
from .search import cpa_table,pair_candidates,rank_candidates
from .terrain import Terrain,CopernicusTerrain,corridor_grid,refine_grid
from .tracks import load_tracks,unix_time


def dump(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n")


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
    bounds=config.get("grid",{}).get("bounds")
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
    grid=config.get("grid",{})
    coarse=grid.get("spacing_m",200)
    crs=grid.get("crs","EPSG:5070")
    points=corridor_grid(tracks,events,coarse,terrain,crs,grid.get("bounds"),origin)
    print(f"Grid: {len(points)} points; {len(tracks)} trajectory segments",flush=True)
    radius=max(event["slant_range_m"][1] for event in events)
    c=config.get("sound_speed_mps",343.0)
    filters=config.get("filters",{})
    def select(points):
        table=cpa_table(tracks,points,radius,c,config.get("cpa_step_s",2))
        candidates,counts=pair_candidates(table,events,
            offset_tolerance_s=filters.get("offset_tolerance_s",5),time_origin=origin,
            time_tolerance_s=filters.get("known_time_tolerance_s",5),silence=filters.get("silence"))
        return candidates,counts
    candidates,counts=select(points)
    dump(output/"filter-counts.json",counts)
    print("Coarse filters:",counts,flush=True)
    if not candidates:
        raise ValueError("No candidates survived; see filter-counts.json")
    points.to_csv(output/"coarse-grid.csv",index=False)
    dump(output/"measured-events.json",events)
    fine=grid.get("scoring_spacing_m",100)
    if fine<coarse:
        ids={candidate["point_id"] for candidate in candidates}
        points=refine_grid(points[points.point_id.isin(ids)],coarse,fine,terrain,crs)
        candidates,fine_counts=select(points)
    else:
        fine_counts=counts
    print("Scoring filters:",fine_counts,flush=True)
    dump(output/"scoring-filter-counts.json",fine_counts)
    scoring=config.get("scoring",{})
    parameters=dict(mode=scoring.get("mode","brightness"),time_origin=origin,
        time_sweep_s=scoring.get("time_sweep_s",5),time_step_s=scoring.get("time_step_s",0.5),c=c)
    ranked=rank_candidates(candidates,points,tracks,events,measurements,**parameters)
    if not ranked:
        raise ValueError("No candidate had complete model support in all event windows")
    dump(output/"ranked-grid.json",ranked)
    # Refine the best location from each flight combination rather than spending
    # every refinement slot on neighbouring points of the winning combination.
    best_pairs={}
    for row in ranked:
        best_pairs.setdefault(tuple(row["flight_ids"]),row)
    chosen=list(best_pairs.values())[:grid.get("refine_pairs",10)]
    final_spacing=grid.get("refine_spacing_m",25)
    if final_spacing<fine:
        seeds=pd.DataFrame(chosen)
        points2=refine_grid(seeds,fine,final_spacing,terrain,crs)
        candidates2,refined_counts=select(points2)
        ranked2=rank_candidates(candidates2,points2,tracks,events,measurements,**parameters)
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
            "ranked_points":len(ranked),"flight_combinations":len(best_pairs),"best":ranked[0],
            "elapsed_s":time.monotonic()-began,
            "scoring_time_is_locked":True}
    dump(output/"report.json",report)
    plot_results(output,ranked,tracks,measurements,c)
    print("Best:",json.dumps(ranked[0]),flush=True)
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
