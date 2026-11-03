"""Count unmodified fit calls at one already scored, automatically selected cell."""
from pathlib import Path
import collections,hashlib,json,time
import numpy as np
from aircraft_geoloc import matching
from aircraft_geoloc.data_access import FlightIndex, content_hash
from aircraft_geoloc.terrain import Terrain
from aircraft_geoloc.tiled_search import SearchBudget, tile_points, _tracks, _expanded_bounds, _score

root=Path('/outputs');job=next(root.glob('jobs/*/result.json')).parent
manifest=json.loads((job/'search/manifest.json').read_text())['configuration']
observation=json.loads((root/'coarse-work-observation.json').read_text())
selected=observation['tiles'][0]['tile']
payload=json.loads((job/'search'/selected).read_text())['payload']
row=max(payload['ranked'],key=lambda r:(len(r.get('event_indices',[])),r['score']))
point_id=row['point_id']
config=json.loads(Path('/inputs/operator.json').read_text())
terrain=Terrain(config['terrain']['rasters'],geoid_raster=config['terrain']['geoid_raster'])
indexes=[FlightIndex(path) for path in config['flight_indexes']]
budget=SearchBudget(**manifest['budget']);events,measurements=matching.prepare_events(manifest['events'])
points=tile_points(payload['cells'],budget.spacing_m,manifest['bounds'],terrain,manifest['crs'])
points=points.loc[points.point_id==point_id];assert len(points)==1
radius=max(e['slant_range_m'][1] for e in events)
tracks=_tracks(indexes,_expanded_bounds(payload['cells'],budget.spacing_m,radius,manifest['crs']),manifest['time_range_s'],budget)
original=matching.fit_ridge;counts=collections.Counter();durations=collections.defaultdict(float)
def counted(track,observer,measurement,start_time,f0_bounds,c=343.,sigma_hz=1.,drift_fraction=.02):
    key=hashlib.sha256()
    key.update(json.dumps([track.id,list(np.asarray(observer)),start_time,list(f0_bounds),c,sigma_hz,drift_fraction],separators=(',',':')).encode())
    for array in [measurement[0].time,measurement[1],measurement[2]]:
        a=np.ascontiguousarray(array);key.update(str((a.dtype.str,a.shape)).encode());key.update(a.tobytes())
    k=key.hexdigest();counts[k]+=1;started=time.perf_counter()
    try:return original(track,observer,measurement,start_time,f0_bounds,c,sigma_hz,drift_fraction)
    finally:durations[k]+=time.perf_counter()-started
matching.fit_ridge=counted
clock=manifest['scoring']['recording_start_window_s']
started=time.perf_counter();rows,work=_score(points,tracks,events,measurements,budget,manifest['scoring'],manifest['filters'],clock);elapsed=time.perf_counter()-started
out={'scope':'single previously scored automatically selected receiver cell, repeated fit inputs counted while executing original scorer; no cache, truth, global sweep or speedup claim',
 'selection':'largest completed coarse checkpoint by bytes, then most matched groups, then highest stored score',
 'tile':selected,'point_id':point_id,'point_lat':float(points.iloc[0].lat),'point_lon':float(points.iloc[0].lon),
 'work':work,'candidate_rows_returned':len(rows),'returned_rows_content_hash':content_hash(rows),
 'fit_calls':sum(counts.values()),'unique_exact_fit_inputs':len(counts),'repeat_fit_calls':sum(counts.values())-len(counts),
 'fit_multiplicities':dict(collections.Counter(counts.values())),
 'fit_elapsed_s':sum(durations.values()),'total_elapsed_s':elapsed,'recording_start_window_s':clock,
 'instrumentation': 'wrapper around matching.fit_ridge in this diagnostic process only; original called for every invocation'}
(root/'one-point-fit-profile.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
