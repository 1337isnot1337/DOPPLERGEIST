"""Time existing acoustic stages on one genuine input without changing decisions."""
import argparse
import json
from pathlib import Path
import time

from dopplergeist import episode_discovery as discovery
from validate_acoustic_episodes import run_case


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--case',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    case=next(c for c in json.loads(args.manifest.read_text())['cases'] if c['id']==args.case)
    log=args.output/'stage-times.jsonl'
    for name in ('_spectrum','_paths','deduplicate','stitch','reconcile'):
        original=getattr(discovery,name)
        def timed(*a,_name=name,_original=original,**kw):
            began=time.monotonic();result=_original(*a,**kw)
            entry=dict(stage=_name,runtime_s=time.monotonic()-began,output_count=len(result) if isinstance(result,list) else None)
            with log.open('a') as stream:stream.write(json.dumps(entry)+'\n')
            return result
        setattr(discovery,name,timed)
    result=run_case(case,args.output,1600.,True)
    result['instrumentation']='stage clocks only; unchanged detector arguments/results'
    (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
