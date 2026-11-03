"""Post-terminal candidate-point/association evaluation; never a search input."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from pyproj import Geod


def evaluate(job, truth):
    result = json.loads((job/'result.json').read_text())
    assert result['status'] in {'succeeded','inconclusive','failed','needs_input','cancelled'}
    search = json.loads((job/'search/search-report.json').read_text())
    labels = json.loads(truth.read_text())
    def overlap(a,b):
        intersection=max(0,min(a['end_s'],b['end_s'])-max(a['start_s'],b['start_s']))
        union=max(a['end_s'],b['end_s'])-min(a['start_s'],b['start_s'])
        return intersection/union
    remaining=list(enumerate(labels['events']))
    associations={}
    joins=[]
    for event in result['events']:
        match=max(remaining,key=lambda pair:overlap(event,pair[1]))
        assert overlap(event,match[1])>0
        remaining.remove(match)
        associations[event['event_id']]=match[1]['flight_id']
        joins.append({'event_id':event['event_id'],'truth_event_index':match[0],
            'interval_iou':overlap(event,match[1]),'true_flight_id':match[1]['flight_id'],
            'detected_interval_s':[event['start_s'],event['end_s']],
            'truth_interval_s':[match[1]['start_s'],match[1]['end_s']]})
    geod=Geod(ellps='WGS84')
    lat,lon=labels['location']
    expected_start=datetime.fromisoformat(labels['recording_start_utc'].replace('Z','+00:00')).timestamp()
    def points(rows):
        output=[]
        for rank,row in enumerate(rows,1):
            error=geod.inv(lon,lat,row['lon'],row['lat'])[2]
            ids=row.get('event_ids') or [result['events'][i]['event_id'] for i in row.get('event_indices',range(len(row['flight_ids'])))]
            correct=[flight==associations[event] for event,flight in zip(ids,row['flight_ids'])]
            start=row.get('recording_start_time_s')
            if start is None and row.get('recording_start_utc'):
                start=datetime.fromisoformat(row['recording_start_utc'].replace('Z','+00:00')).timestamp()
            output.append({'rank':rank,'lat':row['lat'],'lon':row['lon'],'point_error_m':error,
                'point_within_m':{str(t):bool(error<=t) for t in [100,500,1000]},
                'event_ids':ids,'flight_ids':row['flight_ids'],'correct_flight_associations':correct,
                'all_reported_associations_correct':len(ids)==len(row['flight_ids']) and all(correct),
                'matched_groups':len(ids),'clock_offset_from_supplied_truth_s':None if start is None else start-expected_start,
                'score':row['score'],'score_kind':row.get('score_kind')})
        return output
    return {'event_truth_join':joins,'all_product_candidates':points(result.get('candidates',[])),
            'all_search_candidates':points(search.get('ranked',[])),
            'all_coarse_candidates':points(search.get('coarse_ranked',[]))}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--truth',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=evaluate(args.job,args.truth)
    # Refuse accidental overwrites of the frozen evaluation or job outputs.
    with args.output.open('x') as stream:json.dump(data,stream,indent=2,allow_nan=False);stream.write('\n')
