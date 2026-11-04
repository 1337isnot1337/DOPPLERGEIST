"""Summarize saved real-media replays; never run a detector or read flight truth."""
import argparse
from collections import defaultdict
import csv
import gzip
import json
from pathlib import Path


def observed_seconds(data):
    hop=data.get('settings',{}).get('hop_s',.5)
    cells=sorted((p['time_s']-hop/2,p['time_s']+hop/2) for e in data['events'] for p in e['ridge'])
    total=0.; end=0.
    for a,b in cells:
        a=max(0.,a)
        total+=max(0.,b-max(end,a)); end=max(end,b)
    return total


def retained_points(old,new):
    by_time=defaultdict(list)
    for event in new['events']:
        for point in event['ridge']:
            by_time[round(point['time_s'],6)].append(point['frequency_hz'])
    retained=total=0
    for event in old['events']:
        for point in event['ridge']:
            total+=1
            f=point['frequency_hz']
            retained+=any(abs(g-f)<=max(1.,.006*f) for g in by_time.get(round(point['time_s'],6),[]))
    return retained,total


def load(root,case):
    path=root/case/'discovery/discovery.json'
    return json.loads(path.read_text()) if path.exists() else None


def outcomes(root):
    return {r['case_id']:r for r in (json.loads(line) for line in (root/'results.jsonl').read_text().splitlines())}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--new',type=Path,required=True)
    p.add_argument('--wide',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    cases=json.loads(a.manifest.read_text())['cases']
    runs={name:outcomes(root) for name,root in [('baseline',a.baseline),('new',a.new),('wide',a.wide)]}
    rows=[]
    with gzip.open(a.output/'observations.jsonl.gz','wt',encoding='utf8') as stream:
        for case in cases:
            cid=case['id']
            data={name:load(root,cid) for name,root in [('baseline',a.baseline),('new',a.new),('wide',a.wide)]}
            old,new=data['baseline'],data['new']
            kept,total=retained_points(old,new)
            row=dict(case_id=cid,context=case['context'],source_sha256=case['sha256'],
                     baseline_observed_seconds=round(observed_seconds(old),3),new_observed_seconds=round(observed_seconds(new),3),
                     baseline_points_retained=kept,baseline_points_total=total)
            for name in runs:
                result=runs[name].get(cid,{})
                for key in ['status','proposals','child_tracks','runtime_s','peak_rss_kib','output_bytes']:
                    row[name+'_'+key]=result.get(key)
            row['new_brief_proposals']=sum(e['acceptance_path']=='brief_strong_evidence' for e in new.get('episodes',[]))
            row['new_association_work']=new.get('association_pairs')
            row['new_retained_candidates']=new.get('counts',{}).get('provisional_paths')
            row['new_implementation_sha256']=new.get('code',{}).get('implementation_sha256')
            row['new_git_commit']=new.get('code',{}).get('git_commit')
            rows.append(row)
            stream.write(json.dumps(dict(case_id=cid,**data),separators=(',',':'),allow_nan=False)+'\n')
    with (a.output/'comparison.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps(dict(cases=len(rows),output=str(a.output))))


if __name__=='__main__':
    main()
