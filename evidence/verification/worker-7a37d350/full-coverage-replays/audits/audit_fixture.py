"""Bind a stopped full-support fixture to its frozen short-track predecessor."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
from pyproj import Transformer
import soundfile as sf

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def read(path):
    return json.loads(path.read_text())

def audit(previous, current):
    receipt = read(current / 'acceptance.json')
    if receipt.get('stage') != 'complete' or receipt.get('service_and_workers_stopped') is not True:
        raise RuntimeError('Evaluation data remain closed until the final service is stopped')
    generated = read(current / 'evaluation/generation.json')
    source = read(current / 'source-manifest.json')
    checks = {}
    report = {'scope': 'Final-run full-support fixture preservation and independent serialized-motion audit',
        'auditor_sha256': sha(Path(__file__).resolve()), 'previous_run': str(previous), 'current_run': str(current),
        'acceptance_sha256': sha(current / 'acceptance.json'), 'source_manifest_sha256': sha(current / 'source-manifest.json'),
        'generation_manifest_sha256': sha(current / 'evaluation/generation.json'), 'checks': checks,
        'limitations': ['This audits one additional synthetic-input variant, not independent real-world performance.',
            'The analytic support certificate covers nominal CPA receivers; actual profile support is separately gated.']}
    checks['declared_variant_matches'] = receipt.get('fixture_variant') == generated.get('fixture_variant') == 'full-coverage'
    checks['generator_bound_to_executed_source'] = generated['generator_sha256'] == sha(current / 'implementation/scripts/make_multi_event_case.py')
    checks['solver_source_unchanged'] = source['expected_implementation_files'] == read(previous / 'source-manifest.json')['expected_implementation_files']
    files = {}
    for name in ('recording.mp3', 'request.json', 'terrain.tif', 'geoid.tif'):
        old, new = previous / 'fixture/inputs' / name, current / 'fixture/inputs' / name
        files[name] = {'original_sha256': sha(old), 'actual_sha256': sha(new), 'bytes_unchanged': old.read_bytes() == new.read_bytes()}
        checks['generated_' + name + '_bound'] = generated['input_files'][name]['sha256'] == sha(new)
    old_labels, new_labels = previous / 'evaluation/truth/labels.json', current / 'evaluation/truth/labels.json'
    files['labels.json'] = {'original_sha256': sha(old_labels), 'actual_sha256': sha(new_labels), 'bytes_unchanged': old_labels.read_bytes() == new_labels.read_bytes()}
    checks['input_audio_request_terrain_and_labels_preserved'] = all(item['bytes_unchanged'] for item in files.values())
    checks['labels_bound_to_generation'] = generated['truth_sha256'] == sha(new_labels)
    a, ar = sf.read(previous / 'fixture/renderer/recording.wav', dtype='float32')
    b, br = sf.read(current / 'fixture/renderer/recording.wav', dtype='float32')
    checks['rendered_pcm_preserved'] = ar == br == 8000 and np.array_equal(a, b)
    checks['wav_container_bound_to_generation'] = generated['renderer_wav_sha256'] == sha(current / 'fixture/renderer/recording.wav')
    report['input_files'] = files
    report['wav_pcm'] = {'sample_rate_hz': ar, 'samples': len(a), 'pcm_sha256': hashlib.sha256(a.tobytes()).hexdigest(),
        'container_byte_identity_claimed': False, 'reason': 'The FLOAT WAV PEAK chunk carries an encoder timestamp.'}
    audit_tracks(previous, current, generated, report)
    report['audit_passed'] = all(checks.values())
    return report

def audit_tracks(previous, current, generated, report):
    checks = report['checks']
    original = pd.read_parquet(previous / 'evaluation/original-tracks.parquet')
    full = pd.read_parquet(current / 'evaluation/original-tracks.parquet')
    derived = pd.read_parquet(current / 'fixture/inputs/tracks.parquet')
    mapping = read(current / 'evaluation/flight-id-mapping.json')['original_to_opaque']
    derived['flight_id'] = derived.flight_id.map({value:key for key,value in mapping.items()})
    order = lambda frame: frame.sort_values(['flight_id','time_s']).reset_index(drop=True)
    pd.testing.assert_frame_equal(order(full), order(derived), check_exact=True)
    checks['indexed_geometry_and_all_rows_preserved'] = True
    common = full.merge(original[['flight_id','time_s']], on=['flight_id','time_s'], how='inner')
    pd.testing.assert_frame_equal(order(original), order(common), check_exact=True)
    checks['every_original_observation_preserved'] = True
    checks['same_aircraft_inventory'] = set(original.flight_id) == set(full.flight_id)
    checks['generated_original_tracks_bound'] = generated['input_files']['tracks.parquet']['sha256'] == sha(current / 'evaluation/original-tracks.parquet')
    support = generated['trajectory_support']
    coverage = read(current / 'fixture/inputs/coverage.json')
    checks['support_certificate_forwarded_exactly'] = coverage['trajectory_support'] == {key:value for key,value in support.items() if key!='tracks'}
    checks['nominal_domain_explicit'] = support.get('support_scope') == 'nominal_cpa_receiver_domain' and 'no analytic refinement/profile' in support.get('receiver_domain','')
    duration = generated['duration_s']
    cmin, vmax, radius, right, epoch = 338., .4*343., 20000., 300., 1790000000.
    padding = math.ceil((radius+vmax*(duration+right))/(cmin-vmax))+2
    first, last = epoch-padding, epoch+duration+right
    checks['predeclared_support_constants_match'] = (support['minimum_sound_speed_mps']==cmin and support['speed_bound_mps']==vmax
        and support['maximum_candidate_range_m']==radius and support['right_padding_s']==right
        and support['left_padding_s']==padding and support['emission_interval_s']==[first,last])
    checks['triangle_inequality_arrival_bound'] = -padding+(radius+vmax*(duration+right+padding))/cmin < 0
    operator = read(current / 'operator.json')
    checks['actual_nominal_operator_within_support_domain'] = (0 < operator['max_distance_m'] <= radius
        and operator['sound_speed_mps'] >= cmin)
    request = read(current / 'wire-request.json')
    starts = [datetime.fromisoformat(request['time_window'][key].replace('Z','+00:00')).timestamp()
              for key in ('start_utc','end_utc')]
    result = read(current / 'http/result.json')
    used_times = [point['time_s'] for event in result.get('events',[]) for point in event.get('ridge',[])]
    checks['actual_scored_receive_times_inside_certificate'] = starts == [epoch,epoch] and bool(used_times) and all(0 <= t <= duration for t in used_times)
    earth = Transformer.from_crs('EPSG:4979','EPSG:4978',always_xy=True)
    peak = linear_error = velocity_error = 0.
    exact_grid = True
    for identity, frame in full.groupby('flight_id',sort=False):
        times=frame.time_s.to_numpy()
        exact_grid &= bool(np.array_equal(times,np.arange(first,last+1)))
        x=np.column_stack(earth.transform(frame.lon.to_numpy(),frame.lat.to_numpy(),frame.alt_m.to_numpy()))
        phi,lam=np.deg2rad(frame.lat.to_numpy()),np.deg2rad(frame.lon.to_numpy())
        e,n,u=frame.east_mps.to_numpy(),frame.north_mps.to_numpy(),frame.up_mps.to_numpy()
        v=np.column_stack((-np.sin(lam)*e-np.sin(phi)*np.cos(lam)*n+np.cos(phi)*np.cos(lam)*u,
            np.cos(lam)*e-np.sin(phi)*np.sin(lam)*n+np.cos(phi)*np.sin(lam)*u,np.cos(phi)*n+np.sin(phi)*u))
        controls=3*np.diff(x,axis=0)/np.diff(times)[:,None]-v[:-1]-v[1:]
        peak=max(peak,float(np.linalg.norm(v,axis=1).max()),float(np.linalg.norm(controls,axis=1).max()))
        core=original.loc[original.flight_id==identity]
        for anchor,mask in ((core.time_s.min(),times<core.time_s.min()),(core.time_s.max(),times>core.time_s.max())):
            index=int(np.flatnonzero(times==anchor)[0])
            predicted=x[index]+(times[mask]-anchor)[:,None]*v[index]
            linear_error=max(linear_error,float(np.linalg.norm(x[mask]-predicted,axis=1).max()))
            velocity_error=max(velocity_error,float(np.linalg.norm(v[mask]-v[index],axis=1).max()))
    checks['exact_common_time_grid'] = exact_grid
    checks['continuous_speed_bound_independently_verified'] = math.isfinite(peak) and peak < vmax
    checks['all_tail_rows_follow_endpoint_tangents'] = linear_error < 1e-6 and velocity_error < 1e-8
    checks['coordinate_and_height_domain_valid'] = bool(full.lat.between(-85,85).all() and full.lon.between(-180,180).all() and full.alt_m.between(121,20000).all())
    checks['published_maximum_speed_matches_actual'] = math.isclose(peak,support['maximum_hermite_speed_control_mps'],rel_tol=1e-12,abs_tol=1e-8)
    report['motion'] = {'original_rows':len(original),'actual_rows':len(full),'aircraft_count':full.flight_id.nunique(),
        'maximum_continuous_speed_control_mps':peak,'all_tail_position_error_m':linear_error,'all_tail_velocity_error_mps':velocity_error,
        'altitude_range_m':[float(full.alt_m.min()),float(full.alt_m.max())], 'left_padding_s':padding}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('previous',type=Path)
    parser.add_argument('current',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    old,new,out=args.previous.resolve(),args.current.resolve(),args.output.resolve()
    if out.exists() or out.is_relative_to(old) or out.is_relative_to(new):
        raise ValueError('The audit must be a new separate file; original runs stay unchanged')
    result=audit(old,new)
    out.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'output':str(out),'sha256':sha(out),'audit_passed':result['audit_passed'],
        'failed_checks':[key for key,value in result['checks'].items() if not value],'motion':result['motion']}))
