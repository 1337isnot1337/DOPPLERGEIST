import hashlib,json,subprocess,threading,time,urllib.request
from pathlib import Path
import pandas as pd
from aircraft_geoloc.data_access import FlightIndex,write_json
from aircraft_geoloc.jobs import JobManager
from aircraft_geoloc.service import JobServer
out=Path('results/hermes-upload-20261102').resolve()
source=Path('/home/cinna/dopplergeist-w2-data-scale/results/hermes-synthetic-reference-20261102')
epoch=1788897600.
f=pd.read_csv(source/'track.csv');f['flight_id']='synthetic-actor';f['time_s']+=epoch;f['altitude_basis']='orthometric_synthetic'
index=FlightIndex.build(out/'flight-index.sqlite',[f],sources=[{'path':str(source/'track.csv'),'sha256':hashlib.sha256((source/'track.csv').read_bytes()).hexdigest()}],coverage={'bounds':[-180,-90,180,90],'time_range_s':[epoch,epoch+199],'all_aircraft':True,'population':'synthetic actor; no claim of real-world traffic completeness'})
subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(source/'rec.wav'),'-codec:a','libmp3lame',str(out/'recording.mp3')],check=True)
config={'flight_indexes':[str(index.path)],'terrain':{'constant_m':50.},'offline':True,'filters':{'association':'subsets','min_events':1,'max_events':2},'search_budget':{'spacing_m':5000.,'tile_cells':16,'top_k':20,'refine_spacing_m':500.,'refine_finalists':1},'refine_finalists':1}
write_json(out/'operator-configuration.json',config)
manager=JobManager(out/'jobs',config=config,max_runtime_s=1800)
server=JobServer(('127.0.0.1',0),manager);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
base=f'http://127.0.0.1:{server.server_port}'
metadata={'schema_version':1,'search':{'coverage':'conus'},'time_window':{'start_utc':'2026-09-08T20:00:30Z','end_utc':'2026-09-08T20:00:30Z','source':'user','source_detail':'Synthetic recording start declared by independent generator'}}
payload=(out/'recording.mp3').read_bytes();began=time.monotonic()
try:
 request=urllib.request.Request(base+'/api/jobs',payload,headers={'Content-Type':'application/octet-stream','X-Filename':'recording.mp3','X-Dopplergeist-Request':json.dumps(metadata)})
 with urllib.request.urlopen(request,timeout=30) as response: queued=json.load(response)
 write_json(out/'submission.json',queued);print('submitted',queued['job_id'],flush=True)
 final=manager.wait(queued['job_id']);directory=manager.directory(queued['job_id'])
 with urllib.request.urlopen(base+f'/api/jobs/{queued["job_id"]}') as response: readback=json.load(response)
 assert final==readback
 with urllib.request.urlopen(base+f'/api/jobs/{queued["job_id"]}/artifacts/input.mp3') as response: assert response.read()==payload
 summary={'job_id':queued['job_id'],'status':final['status'],'reason_code':final.get('reason_code'),'events':len(final.get('events',[])),'candidates':len(final.get('candidates',[])),'coverage':final.get('coverage'),'elapsed_s':time.monotonic()-began,'upload_sha256':hashlib.sha256(payload).hexdigest(),'original_download_identical':True,'job_directory':str(directory),'search_scope':'CONUS; no coordinate or flight identity supplied in request','limitations':['Independent synthetic reference, not real national localization','Historical query extends beyond supplied synthetic track interval; partial coverage is expected','Constant orthometric ground; no datum-conversion claim']}
 write_json(out/'http-receipt.json',summary);print(json.dumps(summary,indent=2),flush=True)
finally:
 server.shutdown();server.server_close();manager.close();thread.join()
