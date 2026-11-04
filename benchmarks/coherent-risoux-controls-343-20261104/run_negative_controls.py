#!/usr/bin/env python3
"""Execute the predeclared PR 343 whole-recording control supplement once."""
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback

ROOT = Path('/workspace/scratch/e20de6666de2')
APP = ROOT / 'DOPPLERGEIST-pr343-negative-runtime'
REFERENCE = ROOT / 'reference-doppler-locate-ed84e0f'
OVERLAY = ROOT / 'coherent-runtime-343/site-packages'
PYTHON = ROOT / '.venv/bin/python'
APP_SHA = 'cff7d1646932cb9c99fd5fd3c18e2c36d869ad41'
REFERENCE_SHA = 'ed84e0f066d60833f7e9683c286a1f4838e28639'
MANIFEST_SHA = '66d82fbc67afcc1321e76fad1d4530f806943b2890c9fc3c1bd0650cd63922eb'
LIMITS = {'ordinary': 120.0, 'coherent': 300.0}
BATCH_LIMIT = 5400.0


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if hasattr(value, 'tolist'):
        return plain(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return {'nonfinite_float': str(value)}
    return value


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(plain(value), indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def check_source():
    for directory, expected in ((APP, APP_SHA), (REFERENCE, REFERENCE_SHA)):
        actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=directory, text=True).strip()
        dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                        cwd=directory, text=True).strip()
        if actual != expected or dirty:
            raise RuntimeError(f'Pinned source changed: {directory.name}')


@contextmanager
def replaced(owner, name, replacement):
    original = getattr(owner, name)
    setattr(owner, name, replacement)
    try:
        yield
    finally:
        setattr(owner, name, original)


class Audit:
    def __init__(self, output):
        self.output = output
        self.stream = (output / 'observations.jsonl').open('x', buffering=1)
        self.counts = {}

    def emit(self, event, **fields):
        self.counts[event] = self.counts.get(event, 0) + 1
        self.stream.write(json.dumps(plain({'event': event, **fields}), allow_nan=False) + '\n')


def ordinary(audio, output, audit, result):
    from dopplergeist import discovery
    from dopplergeist.intake import intake_recording
    recording = intake_recording(audio, output / 'intake')
    result['decoded'] = {'samples': recording.diagnostics['sample_count'],
                         'sample_rate_hz': recording.metadata['sample_rate_hz'],
                         'duration_s': recording.metadata['duration_s']}
    result['settings'] = asdict(discovery.DiscoverySettings())
    result['spectra'] = []
    spectrum, usable = discovery._spectrum, discovery._usable

    def observe_spectrum(data, sr, start, settings):
        value = spectrum(data, sr, start, settings)
        frames = 0 if value is None else len(value.time)
        row = {'start_s': start, 'decoded_samples': len(data), 'frames': frames,
               'time_span_s': float(value.time[-1] - value.time[0]) if frames else None}
        result['spectra'].append(row)
        audit.emit('ordinary_spectrum', **row)
        return value

    def observe_usable(path, settings):
        accepted = usable(path, settings)
        audit.emit('ordinary_measured_path', points=path, usable=bool(accepted))
        return accepted

    with replaced(discovery, '_spectrum', observe_spectrum), replaced(discovery, '_usable', observe_usable):
        events = discovery.discover_events(recording, output_dir=output / 'discovery', plot_summary=False)
    result['duration_eligible'] = any((s['time_span_s'] or 0) >= 12 for s in result['spectra'])
    return events


def coherent(audio, output, audit, result):
    import numpy as np
    import scipy.fft as fft
    from dopploc import audio as reference_audio, detect, measure
    from dopplergeist.coherent_discovery import events_from_coherent_traces
    spec = importlib.util.spec_from_file_location('coherent_capture', APP / 'scripts/discover_coherent_audio.py')
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    result['settings'] = asdict(detect.Params())
    result['decoded'] = []
    result['spectra'] = []
    active = {'proposal_id': None}
    proposals, fit_results, returned_traces, refined_ids = {}, {}, {}, []
    originals = {name: getattr(detect, name) for name in ('_candidates', '_trace_for', '_refine_all')}
    original_load, original_spectrum = reference_audio.load_audio, reference_audio.spectrogram
    original_ridge = measure.trace_ridge
    original_fft = {name: getattr(fft, name) for name in ('rfft2', 'irfft2')}

    def load(*args, **kwargs):
        value = original_load(*args, **kwargs)
        sr = kwargs.get('sr', 8000)
        row = {'samples': len(value), 'sample_rate_hz': sr, 'duration_s': len(value) / sr,
               'decode_start_s': kwargs.get('start'), 'decode_duration_s': kwargs.get('duration'),
               'coherent_frame_capacity': max(0, 1 + (len(value) - 4000) // 1000)}
        result['decoded'].append(row)
        audit.emit('coherent_decode', **row)
        return value

    def spectrum(*args, **kwargs):
        value = original_spectrum(*args, **kwargs)
        row = {'frames': len(value.t), 'first_time_s': float(value.t[0]) if len(value.t) else None,
               'last_time_s': float(value.t[-1]) if len(value.t) else None, 'hop_s': value.dt}
        result['spectra'].append(row)
        audit.emit('coherent_spectrum', **row)
        return value

    def candidates(*args, **kwargs):
        value = originals['_candidates'](*args, **kwargs)
        # Template arrays are deterministic source data, not measured evidence.
        rows = [{**{k: v for k, v in row.items() if k != 'shape'},
                 'shape': {'v': row['shape'].v, 'tau': row['shape'].tau}}
                for row in value]
        audit.emit('coherent_candidates', candidates=rows)
        return value

    def ridge(*args, **kwargs):
        value = original_ridge(*args, **kwargs)
        t, f, z = value
        audit.emit('coherent_measured_trace', proposal_id=active['proposal_id'],
                   time_s=t, frequency_hz=f, brightness=z)
        return value

    def trace_for(proposal, *args):
        identifier = active['ids'][id(proposal)]
        active['proposal_id'] = identifier
        try:
            value = originals['_trace_for'](proposal, *args)
            returned_traces[identifier] = value
            audit.emit('coherent_trace_for', proposal_id=identifier, returned=value is not None,
                       sample_count=None if value is None else len(value[0]),
                       harmonic=None if value is None else value[2],
                       half_window_s=None if value is None else value[3])
            return value
        finally:
            active['proposal_id'] = None

    class ObservedMap:
        def __init__(self, executor, ids, found):
            self.executor, self.ids = executor, ids
            self.proposals = dict(zip(ids, found))

        def map(self, function, arguments):
            eligible = [i for i in self.ids if returned_traces.get(i) is not None]
            for identifier, value in zip(eligible, self.executor.map(function, arguments)):
                fit_results[identifier] = value
                audit.emit('coherent_fit_result', proposal_id=identifier,
                           fit=None if value is None else value[0],
                           inlier_mask=None if value is None else value[1])
                try:
                    yield value
                finally:
                    # The original refinement loop consumes the fit and updates
                    # this object before requesting the next result.
                    proposal = self.proposals[identifier]
                    trace = getattr(proposal, '_trace', None)
                    audit.emit('coherent_fit_consumed', proposal_id=identifier, proposal=proposal,
                               inlier_time_s=None if trace is None else trace[0],
                               inlier_frequency_hz=None if trace is None else trace[1])

    def refine(found, spectrum_value, settings, executor):
        ids = list(range(len(proposals), len(proposals) + len(found)))
        active['ids'] = {id(p): i for i, p in zip(ids, found)}
        for identifier, proposal in zip(ids, found):
            proposals[identifier] = asdict(proposal)
            audit.emit('coherent_before_refinement', proposal_id=identifier, proposal=proposal)
        originals['_refine_all'](found, spectrum_value, settings, ObservedMap(executor, ids, found))
        for identifier, proposal in zip(ids, found):
            reasons = []
            trace, fit_result = returned_traces.get(identifier), fit_results.get(identifier)
            if trace is None:
                reasons.append('reference_trace_unavailable')
            elif fit_result is None:
                reasons.append('reference_fit_unavailable')
            elif not proposal.refined:
                fit, _ = fit_result
                _, _, harmonic, half = trace
                if abs(fit.t_cpa - proposals[identifier]['t_cpa']) > max(10., .5 * half):
                    reasons.append('reference_cpa_shift')
                if not 6 < fit.v < 290:
                    reasons.append('reference_speed_domain')
                if not 35 < fit.d < 30000:
                    reasons.append('reference_slant_domain')
                if fit.rms > 1.5 * harmonic:
                    reasons.append('reference_fit_rms')
                if not reasons:
                    reasons.append('reference_refinement_declined')
            if hasattr(proposal, '_trace'):
                refined_ids.append(identifier)
            audit.emit('coherent_after_refinement', proposal_id=identifier,
                       proposal=proposal, rejection_reasons=reasons)

    def fft_one(name):
        def wrapped(*args, **kwargs):
            kwargs['workers'] = 1
            return original_fft[name](*args, **kwargs)
        return wrapped

    from contextlib import ExitStack
    with ExitStack() as stack:
        for owner, name, replacement in ((reference_audio, 'load_audio', load),
                (reference_audio, 'spectrogram', spectrum), (measure, 'trace_ridge', ridge),
                (detect, '_candidates', candidates), (detect, '_trace_for', trace_for),
                (detect, '_refine_all', refine), (fft, 'rfft2', fft_one('rfft2')),
                (fft, 'irfft2', fft_one('irfft2'))):
            stack.enter_context(replaced(owner, name, replacement))
        traces = capture.capture_traces(audio, workers=1)
    save(output / 'raw-refined-traces.json', traces)
    if len(traces) != len(refined_ids):
        raise RuntimeError('Refined trace observation lost its proposal correspondence')
    quality = []
    for identifier, row in zip(refined_ids, traces):
        proposal, points = row['proposal'], row['ridge_points']
        reasons = []
        if not proposal['refined']:
            reasons.append('not_refined')
        if len(points) < 40:
            reasons.append('fewer_than_40_inliers')
        rms, frequency = float(proposal['rms']), float(proposal['f_main'])
        if not np.isfinite([rms, frequency]).all() or rms < 0 or frequency <= 0:
            reasons.append('invalid_residual_or_frequency')
        elif rms / frequency > .010:
            reasons.append('normalized_residual_above_0.01')
        quality.append({'proposal_id': identifier, 'samples': len(points),
                        'normalized_residual': rms / frequency if frequency > 0 else None,
                        'quality_gate_passed': not reasons, 'rejection_reasons': reasons})
    save(output / 'adapter-quality.json', quality)
    result['raw_refined_traces'] = len(traces)
    result['adapter_quality_passes'] = sum(row['quality_gate_passed'] for row in quality)
    result['duration_eligible'] = bool(result['spectra']) and all(s['frames'] >= 40 for s in result['spectra'])
    return events_from_coherent_traces(traces)


def worker(args):
    os.sched_setaffinity(0, {args.cpu})
    import importlib.metadata as metadata
    import llvmlite.binding
    pins = {'numpy': '2.3.5', 'scipy': '1.17.0', 'numba': '0.68.1', 'llvmlite': '0.50.0'}
    if sys.version_info[:3] != (3, 12, 14) or any(metadata.version(k) != v for k, v in pins.items()):
        raise RuntimeError('Pinned Python or dependency version changed')
    if llvmlite.binding.llvm_version_info != (22, 1, 0):
        raise RuntimeError('Pinned LLVM version changed')
    result = {'state': 'running', 'method': args.method, 'cpu_affinity': sorted(os.sched_getaffinity(0))}
    audit = Audit(args.output)
    started = time.monotonic()
    exit_code = 1

    def interrupted(_signal, _frame):
        raise InterruptedError('Supervisor interrupted this arm')

    signal.signal(signal.SIGTERM, interrupted)
    try:
        events = globals()[args.method](args.audio, args.output, audit, result)
        save(args.output / 'events.json', events)
        result.update(state='completed', ridges=len(events),
                      groups=len({e['harmonic_group_id'] for e in events}),
                      measured_samples=sum(len(e['ridge']) for e in events))
        exit_code = 0
    except BaseException as error:
        result.update(state='error', error=f'{type(error).__name__}: {error}')
        (args.output / 'error.txt').write_text(traceback.format_exc())
    finally:
        own, children = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
        result.update(wall_s=time.monotonic() - started, cpu_user_s=own.ru_utime + children.ru_utime,
                      cpu_system_s=own.ru_stime + children.ru_stime,
                      process_peak_rss_mib=own.ru_maxrss / 1024,
                      waited_child_peak_rss_mib=children.ru_maxrss / 1024,
                      observation_counts=audit.counts)
        audit.stream.close()
        save(args.output / 'result.json', result)
    return exit_code


def stop_owned_group(process, *, force_group=False):
    if process.poll() is not None and not force_group:
        return
    if getattr(process, '_control_cleanup_started', False):
        return
    process._control_cleanup_started = True
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # A supervisor exit does not prove its fit/decoder children also exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=3)


def run(args):
    began = time.monotonic()
    check_source()
    runtime = {'python': '3.12.14', 'numpy': '2.3.5', 'scipy': '1.17.0',
               'numba': '0.68.1', 'llvmlite': '0.50.0', 'llvm': '22.1.0'}
    for program in ('ffmpeg', 'ffprobe'):
        version = subprocess.check_output(['/usr/bin/' + program, '-version'], text=True).splitlines()[0]
        if not version.startswith(program + ' version 6.1.1-3ubuntu5 '):
            raise RuntimeError(f'Pinned {program} version changed')
        runtime[program] = version
    if sha256(args.manifest) != MANIFEST_SHA:
        raise RuntimeError('Frozen acquisition manifest changed')
    manifest = json.loads(args.manifest.read_text())
    cases = manifest['cases']
    if len(cases) != 12 or len({c['opaque_id'] for c in cases}) != 12:
        raise RuntimeError('Expected exactly twelve distinct frozen cases')
    for case in cases:
        audio = Path(case['audio_path'])
        if (case['state'] != 'verified' or case['crc32_verified'] is not True
                or audio.stat().st_size != case['bytes'] or sha256(audio) != case['sha256']):
            raise RuntimeError(f"Input integrity failed: {case['opaque_id']}")
    args.output.mkdir(parents=True, exist_ok=False)
    launcher = args.output / 'bin'
    launcher.mkdir()
    ffmpeg = launcher / 'ffmpeg'
    ffmpeg.write_text('#!/bin/sh\nexec /usr/bin/ffmpeg -threads 1 -filter_threads 1 -filter_complex_threads 1 "$@"\n')
    ffmpeg.chmod(0o755)
    cache = args.output / 'numba-cache'
    cache.mkdir()
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, (OVERLAY, APP / 'src', REFERENCE / 'src'))),
        NUMBA_NUM_THREADS='1', NUMBA_THREADING_LAYER='workqueue', OMP_NUM_THREADS='1',
        OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1',
        PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1', NUMBA_CACHE_DIR=str(cache),
        PATH=str(launcher) + os.pathsep + os.environ.get('PATH', ''), MPLBACKEND='Agg')
    cpu = min(os.sched_getaffinity(0))
    report = {'state': 'running', 'app_source': APP_SHA, 'reference_source': REFERENCE_SHA,
              'runtime': runtime, 'limits_s': LIMITS, 'batch_limit_s': BATCH_LIMIT, 'cpu': cpu,
              'cases': [{'case_id': c['opaque_id'], 'stratum': c['stratum'], 'source_sha256': c['sha256'],
                         'ordinary': {'state': 'not_started'}, 'coherent': {'state': 'not_started'}} for c in cases]}
    process = None
    prior_termination_handler = signal.getsignal(signal.SIGTERM)

    def interrupted(_signal, _frame):
        # Preserve the owned-group cleanup even if termination is requested again.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise InterruptedError('Batch supervisor received SIGTERM')

    signal.signal(signal.SIGTERM, interrupted)
    try:
        for source_case, case in zip(cases, report['cases']):
            for method in ('ordinary', 'coherent'):
                remaining = BATCH_LIMIT - (time.monotonic() - began)
                if remaining <= 0:
                    report['state'] = 'batch_timeout'
                    return 1
                output = args.output / case['case_id'] / method
                output.mkdir(parents=True)
                case[method] = {'state': 'running', 'output': str(output)}
                save(args.output / 'report.json', report)
                command = [str(PYTHON), str(Path(__file__).resolve()), '--method', method,
                           '--audio', source_case['audio_path'], '--output', str(output), '--cpu', str(cpu)]
                arm_started, timed_out = time.monotonic(), False
                with (output / 'stdout.log').open('x') as stdout, (output / 'stderr.log').open('x') as stderr:
                    process = subprocess.Popen(command, env=environment, stdout=stdout, stderr=stderr,
                                               cwd=args.output, start_new_session=True)
                    try:
                        return_code = process.wait(timeout=min(LIMITS[method], remaining))
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        stop_owned_group(process, force_group=True)
                        return_code = process.returncode
                    finally:
                        stop_owned_group(process, force_group=process.poll() not in (None, 0))
                result_file = output / 'result.json'
                value = json.loads(result_file.read_text()) if result_file.exists() else {'state': 'error', 'error': 'No completed worker result'}
                value.update(output=str(output), process_returncode=return_code,
                             supervisor_wall_s=time.monotonic() - arm_started)
                if timed_out:
                    value['state'] = 'timeout'
                elif return_code != 0 and value['state'] == 'completed':
                    value['state'] = 'error'
                case[method] = value
                save(args.output / 'report.json', report)
                print(f"{case['case_id']} {method}: {value['state']} groups={value.get('groups', 'unknown')}", flush=True)
        check_source()
        report['state'] = 'finished'
        return 0 if all(c[m]['state'] == 'completed' for c in report['cases'] for m in LIMITS) else 1
    except BaseException as error:
        report.update(state='error', error=f'{type(error).__name__}: {error}')
        for case in report['cases']:
            for method in LIMITS:
                if case[method]['state'] == 'running':
                    case[method].update(state='interrupted', error=report['error'])
        raise
    finally:
        try:
            if process is not None:
                stop_owned_group(process)
        finally:
            try:
                report['wall_s'] = time.monotonic() - began
                save(args.output / 'report.json', report)
            finally:
                signal.signal(signal.SIGTERM, prior_termination_handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--method', choices=tuple(LIMITS))
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--cpu', type=int)
    arguments = parser.parse_args()
    if arguments.method:
        if arguments.audio is None or arguments.cpu is None:
            parser.error('Worker requires audio and CPU')
        sys.exit(worker(arguments))
    if arguments.manifest is None:
        parser.error('Batch execution requires the frozen manifest')
    sys.exit(run(arguments))
