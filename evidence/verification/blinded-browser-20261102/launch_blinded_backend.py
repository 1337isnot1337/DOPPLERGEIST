import hashlib,json,os,pathlib,subprocess
root=pathlib.Path.cwd();out=root/'results/blinded-browser-20261102';stage=root/'.artifacts/blinded-inputs';venv=root/'.artifacts/blinded-venv'
base=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-uts','--unshare-ipc','--clearenv','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--dir','/etc','--ro-bind','/etc/fonts','/etc/fonts','--ro-bind','/etc/alternatives','/etc/alternatives','--ro-bind','/etc/ld.so.cache','/etc/ld.so.cache','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(venv),'/venv','--ro-bind',str(stage),'/inputs','--bind',str(out),'/output','--chdir','/output','--setenv','MPLCONFIGDIR','/tmp/mpl','--setenv','OPENBLAS_NUM_THREADS','1','--setenv','PATH','/usr/bin:/bin']
probe='''import aircraft_geoloc,hashlib,json,os,pathlib,subprocess
root=pathlib.Path(aircraft_geoloc.__file__).parent
assert str(root).startswith('/venv/')
for p in ['/home/cinna/DOPPLERGEIST','/home/cinna/DOPPLERGEIST-upload-acceptance','/src','/.git','/benchmarks','/data/synthetic/truth.json']:
    assert not pathlib.Path(p).exists(), p
assert not os.environ.get('GH_TOKEN') and not os.environ.get('GITHUB_TOKEN')
print(json.dumps({'installed_package':str(root),'visible_root':sorted(os.listdir('/')),'mounted_inputs':sorted(os.listdir('/inputs')),'decoder_versions':{name:subprocess.run(['/usr/bin/'+name,'-version'],check=True,capture_output=True,text=True).stdout.splitlines()[0] for name in ['ffprobe','ffmpeg']},'truth_paths_absent':True,'host_authentication_environment_absent':True,'installed_sources_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*.py'))}},indent=2))'''
result=subprocess.run(base+['/venv/bin/python','-c',probe],check=True,capture_output=True,text=True)
(out/'namespace-probe.json').write_text(result.stdout)
command=base+['/venv/bin/python','-m','aircraft_geoloc.cli','serve','--jobs','/output/jobs','--config','/inputs/operator.json','--port','18765','--max-runtime','900']
(out/'server-command.json').write_text(json.dumps(command,indent=2)+'\n')
(out/'backend.pid').write_text(str(os.getpid()))
print('Namespace probe passed; starting installed backend on loopback18765',flush=True)
os.execvp(command[0],command)
