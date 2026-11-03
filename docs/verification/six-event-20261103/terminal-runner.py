from datetime import datetime, timezone
import hashlib,json,os,signal,subprocess,time
from pathlib import Path

root=Path(__file__).resolve().parents[1]
output=root/'results/six-event-cli-isolated-v2-20261103'
output.mkdir(parents=True,exist_ok=False)
inputs=root/'data/six-runtime-inputs'
runtime=root/'.artifacts/capsule-runtime/package'
deps=Path('/home/user/dopplergeist-e2e-20261102/.venv/lib/python3.12/site-packages')
request=json.loads((inputs/'request.json').read_text())
package_manifest=json.loads((root/'.artifacts/installed-runtime-manifest.json').read_text())
input_manifest=json.loads((root/'.artifacts/six-runtime-input-manifest.json').read_text())
for row in input_manifest['files']:
    assert hashlib.sha256((inputs/row['path']).read_bytes()).hexdigest()==row['sha256']
command=['bwrap','--unshare-all','--die-with-parent','--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64',
 '--ro-bind','/etc/ld.so.cache','/etc/ld.so.cache','--ro-bind','/etc/passwd','/etc/passwd','--ro-bind','/etc/group','/etc/group','--ro-bind','/etc/alternatives','/etc/alternatives',
 '--dir','/runtime','--ro-bind',str(runtime),'/runtime/package','--ro-bind',str(deps),'/runtime/deps',
 '--ro-bind',str(inputs),'/inputs','--bind',str(output),'/outputs','--tmpfs','/tmp','--dev','/dev','--proc','/proc',
 '--clearenv','--setenv','PATH','/usr/bin:/bin','--setenv','PYTHONPATH','/runtime/package:/runtime/deps',
 '--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','MPLCONFIGDIR','/outputs/.mpl','--setenv','XDG_CACHE_HOME','/outputs/.cache',
 '--setenv','LANG','C.UTF-8','--setenv','OPENBLAS_NUM_THREADS','1','--setenv','OMP_NUM_THREADS','1','--chdir','/outputs',
 '/usr/bin/python3','-m','aircraft_geoloc.cli','analyze','/inputs/recording.mp3','--start-utc',request['time_window']['start_utc'],
 '--end-utc',request['time_window']['end_utc'],'--time-source','Declared clock in the frozen synthetic fixture',
 '--config','/inputs/operator.json','--jobs','/outputs/jobs','--max-runtime','3600']
receipt={'status':'running','started_utc':datetime.now(timezone.utc).isoformat(),'command':command,
 'runtime_manifest':package_manifest,'input_manifest':input_manifest,'namespace_network':'unshared',
 'full_checkout_visible':False,'truth_mounted':False,'renderer_mounted':False,'auth_environment_inherited':False,
 'scope':'finite synthetic six-flyover development replay; no real national accuracy claim',
 'work_policy':{'job_max_runtime_s':3600,'tile_cells':8,'coarse_spacing_m':2000,'refine_spacing_m':100,'event_cap':None},
 'accuracy_thresholds_m':[100,500,1000]}
(output/'run-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
(output/'runner.py').write_bytes(Path(__file__).read_bytes())
began=time.monotonic()
with (output/'cli.log').open('wb') as log:
    process=subprocess.Popen(['/usr/bin/time','-f','max_rss_kib=%M\nuser_cpu_s=%U\nsystem_cpu_s=%S','-o',str(output/'resource-usage.txt'),'--',*command],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    receipt['host_wrapper_pid']=process.pid
    (output/'run-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'started':True,'wrapper_pid':process.pid,'runtime_code_commit':package_manifest['git_commit'],'wheel_sha256':package_manifest['wheel_sha256'],'output':str(output)}),flush=True)
    try:
        code=process.wait(timeout=3900)
    except subprocess.TimeoutExpired:
        receipt['outer_timeout']=True
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait()
        code=process.returncode
receipt.update(status='terminal',exit_code=code,finished_utc=datetime.now(timezone.utc).isoformat(),elapsed_s=time.monotonic()-began)
receipt['inputs_preserved']=all(hashlib.sha256((inputs/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in input_manifest['files'])
results=list((output/'jobs').glob('*/result.json'))
if len(results)==1:
    result=json.loads(results[0].read_text())
    receipt['job_summary']={'job_id':result['job_id'],'status':result['status'],'reason_code':result.get('reason_code'),'detected_events':len(result.get('events',[])),'candidate_count':len(result.get('candidates',[]))}
(output/'run-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:receipt[k] for k in ['status','exit_code','elapsed_s','inputs_preserved']},indent=2),flush=True)
if 'job_summary' in receipt:print(json.dumps(receipt['job_summary'],indent=2),flush=True)
raise SystemExit(0 if code==0 else 1)
