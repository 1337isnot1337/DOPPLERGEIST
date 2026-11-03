"""Two fresh-process replays of the original four-event discovery, no generation.

Usage: python run_audit.py SOURCE_ROOT AUDIO OUTPUT_ROOT
Uses the invoking interpreter/dependencies and the supplied immutable source.
"""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys

CHILD = r'''
from pathlib import Path
import hashlib,json,os,resource,sys,time
source,audio,output=map(Path,sys.argv[1:])
output.mkdir(exist_ok=False)
sys.path.insert(0,str(source/'src'))
began=time.monotonic(); stages=[]
def stage(name):
    fields={}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('VmRSS:','VmHWM:')):
            key,value,*_=line.split();fields[key.rstrip(':')+'_kib']=int(value)
    stages.append(dict(stage=name,elapsed_s=time.monotonic()-began,ru_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**fields))
stage('python_start')
from aircraft_geoloc.intake import intake_recording
from aircraft_geoloc.discovery import discover_events,DiscoverySettings
stage('imports_complete')
recording=intake_recording(audio,output/'intake')
stage('intake_complete')
events=discover_events(recording,output_dir=output/'discovery')
stage('discovery_and_plots_complete')
code=source/'src/aircraft_geoloc/discovery.py'
receipt={'pid':os.getpid(),'input_sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),'detector_sha256':hashlib.sha256(code.read_bytes()).hexdigest(),'events':len(events),'event_groups':[{'id':e['event_id'],'start_s':e['start_s'],'end_s':e['end_s']} for e in events],'settings':vars(DiscoverySettings()),'stages':stages,'generation_executed':False,'scope':'Intake plus discovery/plots only; no search or location acceptance.'}
(output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'events':len(events),'peak_rss_kib':stages[-1]['ru_maxrss_kib'],'elapsed_s':stages[-1]['elapsed_s']}))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('audio',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();args.output.mkdir(exist_ok=True)
    for i in range(2):
        command=[sys.executable,'-c',CHILD,str(args.source.resolve()),str(args.audio.resolve()),str((args.output/f'fresh-{i+1}').resolve())]
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',MPLBACKEND='Agg')
        completed=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
        (args.output/f'fresh-{i+1}.log').write_text(completed.stdout)
        completed.check_returncode();print(completed.stdout,flush=True)
if __name__=='__main__':main()
