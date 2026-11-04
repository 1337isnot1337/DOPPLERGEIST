"""One-to-one retention comparison on frozen real-recording proposals.

References are old acoustic proposals, not exhaustive labels or aircraft truth.
Only saved observations are read. No signal generation or localization is used.
"""
import argparse
from collections import defaultdict
import csv
import gzip
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment


def union(cells):
    result=[]
    for a,b in sorted(cells):
        a=max(0.,float(a))
        if result and a<=result[-1][1]+1e-8:result[-1][1]=max(b,result[-1][1])
        else:result.append([a,float(b)])
    return result


def overlap(a,b):
    i=j=0;total=0.
    while i<len(a) and j<len(b):
        total+=max(0.,min(a[i][1],b[j][1])-max(a[i][0],b[j][0]))
        if a[i][1]<b[j][1]:i+=1
        else:j+=1
    return total


def catalog(data):
    groups=defaultdict(list)
    for event in data.get('events',[]):groups[event.get('harmonic_group_id',event['event_id'])].append(event)
    episodes={e['proposal_id']:e for e in data.get('episodes',[])}
    result=[]
    for gid,events in sorted(groups.items()):
        hop=data['settings']['hop_s']
        cells=episodes[gid]['observed_intervals_s'] if gid in episodes else union(
            [(p['time_s']-hop/2,p['time_s']+hop/2) for e in events for p in e['ridge']])
        result.append(dict(id=gid,events=events,cells=cells))
    return result


def match(references,predictions):
    scores=np.zeros((len(references),len(predictions)))
    evidence={}
    for i,ref in enumerate(references):
        duration=sum(b-a for a,b in ref['cells'])
        total=sum(len(e['ridge']) for e in ref['events'])
        for j,pred in enumerate(predictions):
            temporal=overlap(ref['cells'],pred['cells'])/duration
            if temporal<.25:continue
            retained=0
            for event in ref['events']:
                for point in event['ridge']:
                    t,f=point['time_s'],point['frequency_hz']
                    retained+=any(abs(q['time_s']-t)<1e-7 and abs(q['frequency_hz']-f)<=max(1.,.006*f)
                                  for e in pred['events'] for q in e['ridge'])
            if retained<3:continue
            fraction=retained/total
            scores[i,j]=fraction+1e-6*temporal
            evidence[i,j]=dict(reference=ref['id'],proposal=pred['id'],matched_points=retained,total_points=total,
                               point_coverage=fraction,temporal_coverage=temporal,
                               start_error_s=pred['cells'][0][0]-ref['cells'][0][0],
                               end_error_s=pred['cells'][-1][1]-ref['cells'][-1][1])
    assignments=linear_sum_assignment(scores,maximize=True) if scores.size else ([],[])
    selected=[evidence[i,j] for i,j in zip(*assignments) if (i,j) in evidence]
    selected_pred={e['proposal'] for e in selected}
    duplicates=sum(predictions[j]['id'] not in selected_pred and np.any(scores[:,j]>0) for j in range(len(predictions)))
    possible_merges=sum(np.sum(scores[:,j]>0)>1 for j in range(len(predictions)))
    return dict(matches=selected,missed_references=[r['id'] for r in references if r['id'] not in {e['reference'] for e in selected}],
                matched_references=len(selected),duplicate_proposals=int(duplicates),
                other_extras=len(predictions)-len(selected)-int(duplicates),possible_merging_proposals=int(possible_merges),
                reference_points=sum(sum(len(e['ridge']) for e in r['events']) for r in references),
                matched_points=sum(e['matched_points'] for e in selected))


def retained_measurements(old,new):
    by_time=defaultdict(list)
    for event in new.get('events',[]):
        for point in event['ridge']:by_time[round(point['time_s'],6)].append(point['frequency_hz'])
    retained=total=0
    for event in old.get('events',[]):
        for point in event['ridge']:
            total+=1;f=point['frequency_hz']
            retained+=any(abs(g-f)<=max(1.,.006*f) for g in by_time.get(round(point['time_s'],6),[]))
    return retained,total


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--legacy',type=Path,required=True)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--repaired',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--wide',type=Path,help='optional separate wider-coverage arm; missing cases remain unattempted')
    args=parser.parse_args();args.output.mkdir(exist_ok=False,parents=True)
    cases=json.loads(args.manifest.read_text())['cases']
    roots=dict(legacy=args.legacy,before=args.before,repaired=args.repaired)
    runs={k:{r['case_id']:r for r in map(json.loads,(p/'results.jsonl').read_text().splitlines())} for k,p in roots.items()}
    rows=[];details=[]
    with gzip.open(args.output/'observations.jsonl.gz','wt') as stream:
        for case in cases:
            cid=case['id'];data={}
            for name,root in roots.items():
                file=root/cid/'discovery/discovery.json'
                data[name]=json.loads(file.read_text()) if file.exists() else dict(events=[],status='failed')
            references=catalog(data['legacy']);stream.write(json.dumps(dict(case_id=cid,**data),separators=(',',':'))+'\n')
            for name in roots:
                proposals=catalog(data[name]);scored=match(references,proposals)
                cells=union([cell for p in proposals for cell in p['cells']])
                row=dict(case_id=cid,context=case['context'],arm=name,reference_proposals=len(references),
                         proposals=len(proposals),children=len(data[name].get('events',[])),
                         observed_seconds=sum(b-a for a,b in cells),**{k:v for k,v in scored.items() if k not in ('matches','missed_references')})
                row['raw_points_retained'],row['raw_points_total']=retained_measurements(data['legacy'],data[name])
                run=runs[name][cid]
                for key in ('status','runtime_s','peak_rss_kib','output_bytes','error'):row[key]=run.get(key)
                row['cpu_time_s']=data[name].get('cpu_time_s')
                row['brief_proposals']=sum(e['acceptance_path']=='brief_strong_evidence' for e in data[name].get('episodes',[]))
                row['association_work']=data[name].get('association_pairs')
                row['joint_refits']=data[name].get('joint_refits')
                rows.append(row);details.append(dict(case_id=cid,arm=name,**scored))
    with (args.output/'comparison.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (args.output/'matches.json').write_text(json.dumps(details,indent=2)+'\n')
    if args.wide:
        wide_runs={r['case_id']:r for r in map(json.loads,(args.wide/'results.jsonl').read_text().splitlines())}
        wide_rows=[];coverage_rows=[]
        with gzip.open(args.output/'wide-observations.jsonl.gz','wt') as stream:
            for case in cases:
                cid=case['id']
                if cid not in wide_runs:continue
                run=wide_runs[cid];file=args.wide/cid/'discovery/discovery.json'
                wide=json.loads(file.read_text()) if file.exists() else dict(events=[],status='failed')
                legacy=json.loads((args.legacy/cid/'discovery/discovery.json').read_text())
                narrow=json.loads((args.repaired/cid/'discovery/discovery.json').read_text())
                proposals=catalog(wide);scored=match(catalog(legacy),proposals)
                row=dict(case_id=cid,context=case['context'],proposals=len(proposals),children=len(wide.get('events',[])),
                         **{k:v for k,v in scored.items() if k not in ('matches','missed_references')})
                for key in ('status','runtime_s','peak_rss_kib','output_bytes','error'):row[key]=run.get(key)
                row['cpu_time_s']=wide.get('cpu_time_s');wide_rows.append(row)
                coverage=match(catalog(narrow),proposals)
                retained,total=retained_measurements(narrow,wide)
                coverage_rows.append(dict(case_id=cid,raw_points_retained=retained,raw_points_total=total,narrow_proposals=len(catalog(narrow)),wide_proposals=len(proposals),
                    **{k:v for k,v in coverage.items() if k not in ('matches','missed_references')},
                    missed_narrow_proposals=json.dumps(coverage['missed_references'])))
                stream.write(json.dumps(dict(case_id=cid,wide=wide),separators=(',',':'))+'\n')
        for filename,output_rows in [('wide.csv',wide_rows),('coverage-comparison.csv',coverage_rows)]:
            with (args.output/filename).open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(output_rows[0]));writer.writeheader();writer.writerows(output_rows)


if __name__=='__main__':main()
