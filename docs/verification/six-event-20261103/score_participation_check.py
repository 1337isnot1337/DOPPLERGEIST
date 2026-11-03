"""Post-run, input-only score-participation check. No truth or global search."""
import json, math
from pathlib import Path

import numpy as np
from pyproj import Transformer
from aircraft_geoloc.data_access import FlightIndex
from aircraft_geoloc.geometry import ecef
from aircraft_geoloc.matching import prepare_events, score_ridges, association_score
from aircraft_geoloc.terrain import Terrain
from aircraft_geoloc.tiled_search import merge_candidates
from aircraft_geoloc.data_access import content_hash

root = Path('/outputs')
jobs = list(root.glob('jobs/*/result.json'))
assert len(jobs) == 1
job = jobs[0].parent
result = json.loads(jobs[0].read_text())
assert result['status'] in {'failed', 'inconclusive', 'succeeded', 'needs_input', 'cancelled'}
search_path = job/'search/search-report.json'
if search_path.exists():
    search = json.loads(search_path.read_text())
    ranking_scope = 'original terminal search report'
else:
    # A work-limit result can precede report publication. Recover completed
    # coarse scores only; this performs no search or coordinate optimization.
    identity = json.loads((job/'search/manifest.json').read_text())['configuration']
    ranked, checkpoints, grid_points = [], 0, 0
    for path in sorted((job/'search').glob('tile-*.json')):
        record = json.loads(path.read_text())
        payload = record['payload']
        assert record['payload_hash'] == content_hash(payload)
        checkpoints += 1
        grid_points += payload.get('grid_points', 0)
        if payload.get('ranked'):
            ranked = merge_candidates(ranked + payload['ranked'], identity['budget']['top_k'])
    search = {'status':'coarse_only_after_terminal', 'ranked':ranked,
              'tile_checkpoints_read':checkpoints, 'coarse_grid_points':grid_points,
              'refinement_complete':False, 'original_job_status':result['status'],
              'original_job_reason_code':result.get('reason_code'),
              'scope':'reconstruction of already-produced coarse scores, never an accepted pipeline result'}
    (root/'coarse-postrun-reconstruction.json').write_text(json.dumps(search,indent=2)+'\n')
    ranking_scope = 'post-terminal reconstruction of completed coarse checkpoints; refinement not assessed'
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
terrain = Terrain(config['terrain']['rasters'], geoid_path=config['terrain']['geoid_raster'])
identity = json.loads((job/'search/manifest.json').read_text())['configuration']
xy = Transformer.from_crs('EPSG:4326', 'EPSG:5070', always_xy=True)
ll = Transformer.from_crs('EPSG:5070', 'EPSG:4326', always_xy=True)
out = {'scope': 'fixed reported location and shared clock; bounded source fits reused; no coordinate/clock optimization, truth, leave-one-out prediction or acceptance change',
       'selection': 'leading search row, plus first all-group row if different',
       'ranking_scope':ranking_scope,
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
