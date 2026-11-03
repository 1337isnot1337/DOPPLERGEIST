import argparse,datetime,hashlib,importlib.util,json,pathlib,re,subprocess,time
root=pathlib.Path('/home/cinna/DOPPLERGEIST');private=root/'.artifacts/bird-feeds'
p=argparse.ArgumentParser();p.add_argument('feed',choices=['cornell-feederwatch','hellgate-ospreys']);p.add_argument('--duration',type=float,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('camera_capture',private/'capture_camera_audio.reference.py');camera=importlib.util.module_from_spec(spec);spec.loader.exec_module(camera)
info=json.loads((private/f'{a.feed}.info.json').read_text());master=private/f'{a.feed}.capture-master.m3u8';audio=a.output/'recording.mp3';url='https://www.youtube.com/watch?v='+info['id'];command=camera.decoder_command(str(master),url,audio,a.duration)
position=command.index('-i');command[position:position]=['-protocol_whitelist','file,http,https,tcp,tls,crypto']
command[command.index('-loglevel')+1]='info'
command+=['-t',str(a.duration),'-map','0:v:0','-vf',"trim=duration="+str(a.duration)+",select='isnan(prev_selected_t)+gte(t-prev_selected_t,120)',showinfo",'-vsync','vfr','-frames:v','3','-an',str(a.output/'clock-frame-%03d.png')]
receipt={'feed':a.feed,'source_page':{'cornell-feederwatch':'https://www.allaboutbirds.org/cams/cornell-lab-feederwatch/','hellgate-ospreys':'https://www.allaboutbirds.org/cams/hellgate-ospreys/'}[a.feed],'youtube_id':info['id'],'source_public':info.get('availability')=='public','source_is_live':info.get('is_live'),'capture_begin_utc':now(),'requested_duration_s':a.duration,'manifest_sha256':digest(master),'provider_audio_playlist_sha256':digest(private/f'{a.feed}.audio.m3u8'),'provider_audio_pdt_present':'#EXT-X-PROGRAM-DATE-TIME:' in (private/f'{a.feed}.audio.m3u8').read_text(),'recording_start_utc':None,'recording_clock_established':False,'location_validation_eligible':False,'command':command,'video_saved':False,'snapshot_frames_only':True,'capture_script_sha256':digest(pathlib.Path(__file__)),'timestamp_preservation_command_sha256':digest(private/'capture_camera_audio.reference.py')}
start=time.monotonic()
try:
 with (a.output/'ffmpeg.log').open('wb') as log:r=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=log,timeout=a.duration+90)
 receipt['returncode']=r.returncode;receipt['status']='captured' if r.returncode==0 else 'failed'
 if audio.exists() and audio.stat().st_size:
  receipt['audio_sha256']=digest(audio);receipt['audio_bytes']=audio.stat().st_size;receipt['decoded_duration_s']=camera.decoded_duration(audio)
except Exception as e:receipt.update(status='failed',error=str(e))
receipt['capture_end_utc']=now();receipt['elapsed_s']=time.monotonic()-start
# Public stream URLs carry transient tokens in path segments; no such URL is
# emitted or copied into the public receipt. Raw logs remain local/ignored.
if (a.output/'ffmpeg.log').exists():
 text=(a.output/'ffmpeg.log').read_text(errors='replace');redacted=re.sub(r'https?://[^\s\x27\x22]+','[transient-media-url-omitted]',text)
 (a.output/'ffmpeg-redacted.log').write_text(redacted);receipt['raw_log_sha256']=digest(a.output/'ffmpeg.log')
 receipt['clock_frame_pts_s']=[float(v) for v in re.findall(r'Parsed_showinfo[^\n]*pts_time:([0-9.\-]+)',text)]
(a.output/'capture.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:receipt.get(k) for k in ['feed','status','returncode','requested_duration_s','decoded_duration_s','elapsed_s','provider_audio_pdt_present','audio_sha256','error']}))
