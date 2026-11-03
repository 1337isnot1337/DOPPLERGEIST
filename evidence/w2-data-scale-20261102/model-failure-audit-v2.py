import json,time
from pathlib import Path
import numpy as np
from aircraft_geoloc.audio import Spectrum
from aircraft_geoloc.data_access import FlightIndex,write_json
from aircraft_geoloc.search import cpa_table,pair_candidates,score_candidate
from aircraft_geoloc.terrain import Terrain
from aircraft_geoloc.tiled_search import grid_tiles,tile_points,_expanded_bounds
root=Path('results/w2-model-failure-audit-v2-20261103');began=time.monotonic()
old=json.loads(Path('results/w2-national-v2-20261102/search/scale-report.json').read_text())
index=FlightIndex('results/w2-index-v2-20261102/conus-alltypes.sqlite');start,end=index.report['coverage']['time_range_s'];center=(end-start)/2
samples=np.linspace(center-20,center+20,41);ridge=120*(1-.12*np.tanh((samples-center)/12));spec=Spectrum(samples,np.array([80.,160.]),np.zeros((2,len(samples))),np.zeros((2,len(samples))))
event={'start_s':float(samples[0]),'end_s':float(samples[-1]),'cpa_receive_s':center,'speed_range_mps':[1,308],'slant_range_m':[1,20000],'f0_range_hz':[50,250]}
failed={r['tile'] for r in old['tile_failures']};failures={};checked=0;finite=0
for name,cells in grid_tiles(old['scope'],20000,8):
 if name not in failed:continue
 points=tile_points(cells,20000,old['scope'],Terrain(constant_m=0),'EPSG:5070');lookup={p.point_id:p for p in points.itertuples()}
 for track in index.query(_expanded_bounds(cells,20000,20000,'EPSG:5070'),(start,end)):
  table=cpa_table([track],points,20000,343,2)
  candidates,_=pair_candidates(table,[event],time_origin=start,time_tolerance_s=5)
  for candidate in candidates:
   try:
    row=score_candidate(candidate,lookup[candidate['point_id']],{track.id:track},[event],[(spec,ridge,np.ones(len(samples)),{})],mode='ridge',time_origin=start,time_sweep_s=0);checked+=1;finite+=int(np.isfinite(row['score']))
   except ValueError as error:
    speed=np.linalg.norm(track.speed_vector(np.linspace(track.time[0],track.time[-1],1001)),axis=1)
    entry=failures.setdefault(track.id,{'flight_id':track.id,'typecode':track.typecode,'altitude_basis':sorted(set(track.altitude_basis)),'reason':str(error),'sampled_max_hermite_speed_mps':float(speed.max()),'recorded_max_knot_speed_mps':float(np.linalg.norm(track.speed_vector(track.time),axis=1).max()),'tiles':[]})
    if name not in entry['tiles']:entry['tiles'].append(name)
report={'scope':'Audit of failed analytic-ridge traffic-scale tiles; not localization evaluation','input_index_hash':index.report['input_hash'],'failures':list(failures.values()),'non_exception_candidates_checked':checked,'finite_score_candidates':finite,'nonfinite_score_candidates':checked-finite,'elapsed_s':time.monotonic()-began,'limitation':'Legacy input imputed null motion values as finite zeros; no inference of actual supersonic aircraft is justified. Fresh raw traces are needed for repair.'}
write_json(root/'report.json',report);print(json.dumps(report,indent=2))
