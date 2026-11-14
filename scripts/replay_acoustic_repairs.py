"""Bounded parallel replay; reuse only completed compatible real-input cases.

Existing output directories are immutable. Reused cases are linked from a new
index, preserving their measured costs and source identity. No media is generated.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reuse',type=Path)
    p.add_argument('--max-frequency-hz',type=float,default=1600.)
    p.add_argument('--jobs',type=int,default=4,choices=range(1,5))
    p.add_argument('--timeout-s',type=int,default=600,choices=range(1,1801))
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    cases=json.loads(args.manifest.read_text())['cases'];results={}
    env=dict(os.environ,PYTHONPATH=str(args.source_root.resolve()/'src'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MPLBACKEND='Agg')
    probe="import json;from dopplergeist import episode_discovery as d;print(json.dumps(dict(code=d._code_identity(),settings=d.asdict(d.DiscoverySettings(max_frequency_hz="+repr(args.max_frequency_hz)+")))))"
    expected=json.loads(subprocess.check_output([sys.executable,'-c',probe],env=env,cwd=args.source_root,text=True))
    if args.reuse:
        for line in (args.reuse/'results.jsonl').read_text().splitlines():
            r=json.loads(line);case=next(c for c in cases if c['id']==r['case_id'])
            if r['status']!='complete':continue
            root=args.reuse/case['id'];a=json.loads((root/'discovery/discovery.json').read_text())
            if a.get('status')!='complete' or a['source_sha256']!=case['sha256']:continue
            if a['settings']!=expected['settings'] or a['code']['implementation_sha256']!=expected['code']['implementation_sha256']:continue
            # The exact source identity/configuration of all reused cases must
            # agree. Fresh cases are checked against these identities below.
            r['reused_from']=str(root.resolve());results[case['id']]=r
            (args.output/case['id']).symlink_to(root.resolve(),target_is_directory=True)
    env=dict(os.environ,PYTHONPATH=str(args.source_root.resolve()/'src'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MPLBACKEND='Agg')
    runner=Path(__file__).with_name('validate_acoustic_episodes.py').resolve()
    def run(case):
        command=[sys.executable,str(runner),'--manifest',str(args.manifest.resolve()),'--source-root',str(args.source_root.resolve()),
                 '--output',str((args.output/case['id']).resolve()),'--max-frequency-hz',str(args.max_frequency_hz),'--experimental-episodes','--case',case['id']]
        try:
            process=subprocess.run(command,env=env,capture_output=True,text=True,timeout=args.timeout_s)
            result=json.loads(process.stdout) if process.returncode==0 else dict(case_id=case['id'],status='failed',error=process.stderr[-2000:])
        except subprocess.TimeoutExpired:
            result=dict(case_id=case['id'],status='failed',error=f'Replay exceeded{args.timeout_s}s wall budget')
        print(case['id'],result['status'],result.get('proposals'),round(result.get('runtime_s',0),2),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for result in pool.map(run,sorted([c for c in cases if c['id'] not in results],key=lambda c:-Path(c['path']).stat().st_size)):results[result['case_id']]=result
    rows=[results[c['id']] for c in cases]
    # Preserve every outcome even if the arm is incompatible or all scans fail.
    (args.output/'results.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (args.output/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
    identities=set();configs=set()
    for case in cases:
        root=args.output/case['id'];file=root/'discovery/discovery.json'
        if results[case['id']]['status']=='complete':
            a=json.loads(file.read_text());identities.add(a['code']['implementation_sha256']);configs.add(json.dumps(a['settings'],sort_keys=True))
            if a['source_sha256']!=case['sha256']:raise ValueError('Source checksum changed')
    if identities and (identities!={expected['code']['implementation_sha256']} or configs!={json.dumps(expected['settings'],sort_keys=True)}):raise ValueError('Mixed implementation/configuration: replay cannot be compared as one arm')
    print(json.dumps(dict(cases=len(rows),completed=sum(r['status']=='complete' for r in rows),jobs=args.jobs,implementation_sha256=list(identities))),flush=True)


if __name__=='__main__':main()
