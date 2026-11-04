"""Paired acoustic-only replay of a predeclared real-media manifest.

No downloads, fabricated signals, source identity labels or localization inputs
enter discovery. Each case runs in a fresh process for comparable peak RSS.
Episode discovery requires --experimental-episodes; the default replays the
standard detector, including when --source-root points to a historical checkout.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run_case(case, output, upper, experimental=False):
    if experimental:
        from dopplergeist.episode_discovery import DiscoverySettings, discover_events
    else:
        from dopplergeist.discovery import DiscoverySettings, discover_events
    from dopplergeist.intake import intake_recording
    from dopplergeist.resource_usage import process_peak_rss_kib
    began = time.monotonic()
    settings = DiscoverySettings(max_frequency_hz=upper)
    rate = next(rate for rate in (4000, 8000, 16000, 32000) if upper <= rate * .45)
    result = dict(case_id=case['id'], source_sha256=case['sha256'], experimental_episodes=experimental)
    try:
        with Path(case['path']).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != case['sha256']:
                raise ValueError('Real input checksum differs from frozen manifest')
        intake_options = dict(resample_filter_size=64) if experimental else {}
        recording = intake_recording(case['path'], output / 'intake', sample_rate_hz=rate, **intake_options)
        events = discover_events(recording, output_dir=output / 'discovery', settings=settings, plot_summary=True)
        groups = sorted({e.get('harmonic_group_id', e['event_id']) for e in events})
        result.update(status='complete', duration_s=recording.metadata['duration_s'],
                      proposals=len(groups), child_tracks=len(events),
                      intervals=[dict(group=g, intervals_s=[[e['start_s'],e['end_s']] for e in events if e.get('harmonic_group_id',e['event_id'])==g]) for g in groups])
        data = json.loads((output / 'discovery/discovery.json').read_text())
        result['counts'] = data.get('counts', {})
        result['rejections'] = data.get('rejections', {})
    except Exception as exc:
        result.update(status='failed', error_type=type(exc).__name__, error=str(exc))
    result.update(runtime_s=time.monotonic()-began, peak_rss_kib=process_peak_rss_kib(),
                  output_bytes=sum(p.stat().st_size for p in (output / 'discovery').glob('*') if p.is_file()))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-frequency-hz',type=float,default=1600)
    parser.add_argument('--experimental-episodes',action='store_true',help='replay the experimental episode detector')
    parser.add_argument('--case',help=argparse.SUPPRESS)
    args=parser.parse_args()
    cases=json.loads(args.manifest.read_text())['cases']
    if args.case:
        case=next(c for c in cases if c['id']==args.case)
        print(json.dumps(run_case(case,args.output,args.max_frequency_hz,args.experimental_episodes),allow_nan=False))
        return
    args.output.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,PYTHONPATH=str(args.source_root.resolve()/'src'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MPLBACKEND='Agg')
    results=[]
    for case in cases:
        command=[sys.executable,str(Path(__file__).resolve()),'--manifest',str(args.manifest.resolve()),
                 '--source-root',str(args.source_root.resolve()),'--output',str(args.output.resolve()/case['id']),
                 '--max-frequency-hz',str(args.max_frequency_hz),'--case',case['id']]
        if args.experimental_episodes:
            command.append('--experimental-episodes')
        process=subprocess.run(command,capture_output=True,text=True,env=env,timeout=600)
        if process.returncode:
            result=dict(case_id=case['id'],status='failed',error=process.stderr[-2000:])
        else:
            result=json.loads(process.stdout)
        results.append(result)
        with (args.output/'results.jsonl').open('a') as stream:
            stream.write(json.dumps(result,allow_nan=False)+'\n')
        print(case['id'],result['status'],result.get('proposals'),round(result.get('runtime_s',0),2),flush=True)
    (args.output/'summary.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':
    main()
