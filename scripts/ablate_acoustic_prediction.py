"""Controlled prediction ablation on real recordings, not normal discovery.

Use before-root3447e33. Only full original chunk contexts intersecting the six
predeclared diagnostic targets are evaluated. No target windows or labels are
supplied to normal discovery. No samples or coordinate curves are generated.
"""
import importlib.util,inspect,json,sys,time
from pathlib import Path
import numpy as np
from dopplergeist import episode_discovery as repair
from dopplergeist import episodes
from dopplergeist.intake import IntakeRecording
import argparse
parser=argparse.ArgumentParser(description='Prediction-only ablation on identical real decoded samples, spectra and selected peaks. Use pinned PR3447e33 for --before-root.')
parser.add_argument('--before-root',type=Path,required=True)
parser.add_argument('--pcm-cache',type=Path,required=True)
parser.add_argument('--references',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=False)
spec=importlib.util.spec_from_file_location('dopplergeist.before',str(args.before_root/'src/dopplergeist/discovery.py'));before=importlib.util.module_from_spec(spec);sys.modules[spec.name]=before;spec.loader.exec_module(before)
spec=importlib.util.spec_from_file_location('dopplergeist.before_episodes',str(args.before_root/'src/dopplergeist/episodes.py'));be=importlib.util.module_from_spec(spec);sys.modules[spec.name]=be;spec.loader.exec_module(be)
code=inspect.getsource(before._paths);a=code.index('            slopes = []');b=code.index('            allowed &= costs <= 1',a)
code=code[:a]+'''            allowed = np.abs(speed) <= np.maximum(8,last[:,1,None]*.08)
            predictions = [forecast(path,time,settings) for path in active]
            means = np.array([p[0] for p in predictions])
            tolerance = np.array([p[1] for p in predictions])
            costs = np.abs(frequencies[None,:]-means[:,None])/tolerance[:,None]
'''+code[b:];ns=dict(vars(before),forecast=episodes.forecast);exec(code,ns);soft=ns['_paths']
r=args.pcm_cache;recording=IntakeRecording(r/'recording.f32',json.loads((r/'recording.json').read_text()),{})
legacy=json.loads(args.references.read_text());targets={e['event_id']:e for e in legacy['events']};names=['event-0001','event-0002','event-0004','event-0009','event-0014','event-0016'];rows={n:dict(reference=n,points=len(targets[n]['ridge']),variants={}) for n in names}
def count(e,p):
 t=np.array([q['time_s'] for q in e['ridge']]);f=np.array([q['frequency_hz'] for q in e['ridge']]);idx=np.clip(np.searchsorted(p[:,0],t),0,len(p)-1);return int(np.sum((abs(p[idx,0]-t)<1e-7)&(abs(p[idx,1]-f)<=np.maximum(1.,.006*f))))
s=before.DiscoverySettings();began=time.monotonic()
for start,data in recording.iter_chunks(s.chunk_s,s.overlap_s):
 if not any(targets[n]['start_s']<start+len(data)/recording.metadata['sample_rate_hz'] and targets[n]['end_s']>start for n in names):continue
 spectrum=before._spectrum(data,recording.metadata['sample_rate_hz'],start,s)
 for variant,fn in [('hard_gate',before._paths),('prediction_only',soft)]:
  for path in fn(spectrum,s):
   p=np.asarray(path)
   if len(p)<4:continue
   for name in names:
    k=count(targets[name],p)
    previous=rows[name]['variants'].get(variant,{}).get('matched_points',0)
    if k>previous:
     old_metrics,old_reasons=be.motion(p,s);new_metrics,new_reasons=episodes.motion(p,repair.DiscoverySettings())
     rows[name]['variants'][variant]=dict(matched_points=k,observations=len(p),old_motion=old_metrics,old_rejections=old_reasons,repaired_motion=new_metrics,repaired_rejections=new_reasons)
result=dict(controls='Identical decoded samples, spectrum, normalization, peak selection, assignment and gap limit; replace prediction tolerance alone. Motion checks then applied separately to the same measured paths.',runtime_s=time.monotonic()-began,rows=list(rows.values()))
(out/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
for row in rows.values():print(row['reference'],{k:(v['matched_points'],v['old_motion']['prediction_error_q95'],v['repaired_motion']['prediction_error_q95']) for k,v in row['variants'].items()})
