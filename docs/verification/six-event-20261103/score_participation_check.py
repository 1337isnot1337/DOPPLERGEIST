"""Post-run, input-only score-participation check. No truth or global search."""
import json, math
from pathlib import Path

import numpy as np
from pyproj import Transformer
from aircraft_geoloc.data_access import FlightIndex
from aircraft_geoloc.geometry import ecef
from aircraft_geoloc.matching import prepare_events, score_ridges, association_score
from aircraft_geoloc.terrain import Terrain

root = Path('/outputs')
jobs = list(root.glob('jobs/*/result.json'))
assert len(jobs) == 1
job = jobs[0].parent
result = json.loads(jobs[0].read_text())
assert result['status'] in {'failed', 'inconclusive', 'succeeded', 'needs_input', 'cancelled'}
search = json.loads((job/'search/search-report.json').read_text())
discovery = json.loads((job/'discovery/discovery.json').read_text())
events, measurements = prepare_events(discovery['events'])
rows = search.get('ranked', [])
# Predeclared selection: the leading search row and the first all-group row,
# if distinct. No true identity/location enters selection.
selected = rows[:1]
full = next((r for r in rows if len(r.get('event_indices', [])) == len(events)), None)
if full is not None and (not selected or full != selected[0]): selected.append(full)
config = json.loads(Path('/inputs/operator.json').read_text())
index = FlightIndex(config['flight_indexes'][0])
terrain = Terrain(config['terrain']['rasters'], geoid_raster=config['terrain']['geoid_raster'])
identity = json.loads((job/'search/manifest.json').read_text())['configuration']
xy = Transformer.from_crs('EPSG:4326', 'EPSG:5070', always_xy=True)
ll = Transformer.from_crs('EPSG:5070', 'EPSG:4326', always_xy=True)
out = {'scope': 'fixed reported location and shared clock; bounded source fits reused; no coordinate/clock optimization, truth, leave-one-out prediction or acceptance change',
       'selection': 'leading search row, plus first all-group row if different',
       'proposed_group_count': len(events), 'candidate_checks': []}
for row in selected:
    indices = row.get('event_indices', list(range(len(events))))
    chosen_events = [events[i] for i in indices]
    chosen_measurements = [measurements[i] for i in indices]
    margin = 0.7
    bounds = (row['lon']-margin, row['lat']-margin, row['lon']+margin, row['lat']+margin)
    tracks = {t.id: t for t in index.query(bounds, identity['time_range_s'])}
    chosen_tracks = [tracks[f] for f in row['flight_ids']]
    x, y = xy.transform(row['lon'], row['lat'])
    evaluations = []
    for dx, dy in [(0,0), (100,0), (-100,0), (0,100), (0,-100)]:
        lon, lat = ll.transform(x+dx, y+dy)
        elev = float(terrain.sample(np.array([lat]), np.array([lon]))[0])
        score = score_ridges(chosen_tracks, chosen_events, chosen_measurements,
                             ecef(lat, lon, elev), row['recording_start_time_s'])
        association = association_score(score, chosen_events)
        contributions = []
        for event, residual in zip(chosen_events, score['event_scores']):
            single = association_score({'score':residual, 'event_scores':[residual]}, [event])
            contributions.append(single['score'])
        evaluations.append({'dx_m':dx, 'dy_m':dy, 'lat':lat, 'lon':lon,
                            'shared_recording_start_s':row['recording_start_time_s'],
                            'raw_residual_score':score['score'], 'raw_event_scores':score['event_scores'],
                            'normalized_group_contributions':contributions,
                            'association_score':association['score']})
    base = evaluations[0]
    max_change = [max(abs(e['raw_event_scores'][j]-base['raw_event_scores'][j]) for e in evaluations[1:]) for j in range(len(indices))]
    out['candidate_checks'].append({'event_indices':indices, 'flight_ids':row['flight_ids'],
        'stored_search_score':row['score'], 'recomputed_search_score':base['association_score'],
        'recomputed_score_difference':base['association_score']-row['score'],
        'sum_of_group_contributions':sum(base['normalized_group_contributions']),
        'all_group_contributions_finite':all(math.isfinite(v) for v in base['normalized_group_contributions']),
        'max_event_residual_change_over_100m_offsets_hz':max_change,
        'evaluations':evaluations})
def finite(value):
    if isinstance(value, dict): return {k:finite(v) for k,v in value.items()}
    if isinstance(value, list): return [finite(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value): return None
    return value
(root/'score-participation-check.json').write_text(json.dumps(finite(out), indent=2, allow_nan=False)+'\n')
print(json.dumps({'candidate_checks':len(out['candidate_checks']), 'groups_proposed':len(events)}))
