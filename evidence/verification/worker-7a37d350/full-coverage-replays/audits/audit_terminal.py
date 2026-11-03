"""Independent read-only terminal evidence audit; no pipeline execution."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
from datetime import datetime, timezone

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

def read(path):
    return json.loads(path.read_text())

def inventory(base, files):
    errors, total = [], 0
    for name, expected in files.items():
        relative, path = Path(name), base / name
        if (relative.is_absolute() or '..' in relative.parts or path.is_symlink()
                or not path.is_file() or not path.resolve().is_relative_to(base.resolve())):
            errors.append({'path': name, 'reason': 'missing_or_unsafe'})
            continue
        size, actual = path.stat().st_size, digest(path)
        total += size
        if size != expected['bytes'] or actual != expected['sha256']:
            errors.append({'path': name, 'reason': 'bytes_or_hash_differ'})
    return {'declared_files': len(files), 'verified_files': len(files)-len(errors),
            'verified_bytes': total, 'errors': errors}

def audit(run, repository, equivalent_commit=None, expected_tree=None):
    receipt = read(run / 'acceptance.json')
    if receipt.get('stage') != 'complete' or receipt.get('service_and_workers_stopped') is not True:
        raise RuntimeError('Nonterminal evidence: evaluation labels remain closed')
    checks = {}
    report = {'schema_version': 1, 'scope': 'independent_terminal_binding_and_finite_retention_audit',
        'created_utc': datetime.now(timezone.utc).isoformat(), 'run': str(run),
        'auditor_sha256': digest(Path(__file__).resolve()),
        'receipt_sha256': digest(run / 'acceptance.json'), 'checks': checks,
        'limitations': ['No pipeline, acoustic fit or physical trial is rerun.',
            'Lifecycle ordering is bound to persisted receipts, not newly observed live process handles.',
            'No continuous-space uniqueness, calibrated uncertainty or independent real-world accuracy is established.']}
    manifest_path = run / 'artifact-manifest.json'
    manifest = read(manifest_path)
    report['artifact_inventory'] = inventory(run, manifest['files'])
    checks['all_manifest_files_verified'] = not report['artifact_inventory']['errors']
    expected = receipt['artifact_manifest']
    checks['manifest_bound_to_receipt'] = expected['sha256'] == digest(manifest_path) and expected['bytes'] == manifest_path.stat().st_size
    actual_names = {p.relative_to(run).as_posix() for p in run.rglob('*') if p.is_file()
        and p.name not in {'acceptance.json', 'artifact-manifest.json'}
        and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    missing, extra = sorted(set(manifest['files'])-actual_names), sorted(actual_names-set(manifest['files']))
    report['inventory_membership'] = {'missing': missing, 'unexpected': extra}
    checks['inventory_membership_complete'] = not missing and not extra
    audit_source(run, repository, receipt, report, equivalent_commit, expected_tree)
    audit_job(run, receipt, report)
    report['audit_passed'] = all(checks.values())
    return report

def audit_source(run, repository, receipt, report, equivalent_commit=None, expected_tree=None):
    checks = report['checks']
    source = read(run / 'source-manifest.json')
    report['source_inventory'] = inventory(run / 'implementation', source['files'])
    checks['source_inventory_verified'] = not report['source_inventory']['errors']
    aggregate = hashlib.sha256()
    for name, item in sorted(source['files'].items()):
        aggregate.update(name.encode()+b'\0'+item['sha256'].encode()+b'\0')
    checks['source_snapshot_digest_verified'] = aggregate.hexdigest() == source['snapshot_sha256']
    checks['source_manifest_bound_to_receipt'] = source == receipt['implementation']
    commit, project_errors = source['git']['commit'], []
    audit_commit = equivalent_commit or commit
    tree = subprocess.check_output(['git','-C',str(repository),'rev-parse',audit_commit+'^{tree}'],text=True).strip()
    if equivalent_commit and (not expected_tree or tree != expected_tree):
        raise ValueError('Equivalent source commit requires an independently verified matching tree')
    for name, expected_blob in source['audited_git_blobs'].items():
        content = subprocess.check_output(['git', '-C', str(repository), 'cat-file', 'blob', audit_commit+':'+name])
        actual_blob = hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        if actual_blob != expected_blob or (run / 'implementation' / name).read_bytes() != content:
            project_errors.append(name)
    project_names = [name for name in source['files'] if '.egg-info/' not in name]
    for name in project_names:
        origin = 'scripts/ci_checkpoint_replay.py' if name == 'ci_checkpoint_replay.py' else name
        content = subprocess.check_output(['git','-C',str(repository),'cat-file','blob',audit_commit+':'+origin])
        if (run / 'implementation' / name).read_bytes() != content:
            project_errors.append(name)
    checks['snapshot_project_files_match_committed_source'] = not project_errors and not source['git']['status']
    report['source'] = {'commit': commit, 'snapshot_sha256': source['snapshot_sha256'],
        'tree': tree, 'audited_against_commit': audit_commit,
        'equivalence_scope': 'Exact source tree; commit history is not asserted equivalent.',
        'audited_project_files': len(project_names), 'project_mismatches': sorted(set(project_errors))}

def audit_job(run, receipt, report):
    checks = report['checks']
    source = receipt['implementation']
    http, final = read(run / 'http/http-verification.json'), read(run / 'http/result.json')
    service = http['service']
    job = run / 'http/jobs' / http['job_id']
    checks['http_receipt_bound'] = receipt['http_verification'] == http
    checks['terminal_result_bound'] = final == read(job / 'result.json')
    checks['clean_service_stop'] = (service['shutdown_signal'] == 'SIGINT' and service['returncode'] == 0
        and service['forced_kill'] is False and http.get('interrupted') is False
        and http.get('interruption_signal') is None and http.get('terminal_result_preserved_after_shutdown') is True)
    parse = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))
    checks['truth_opened_after_stop'] = (parse(service['stopped_utc']) <= parse(receipt['analysis_stopped_utc'])
        <= parse(receipt['evaluation_truth_load_started_utc']) <= parse(receipt['evaluation_truth_loaded_utc']))
    checks['http_source_matches_snapshot'] = http['implementation_files'] == source['expected_implementation_files']
    package_hashes = {path.name: digest(path) for path in (run / 'implementation/src/aircraft_geoloc').glob('*.py')}
    checks['snapshot_package_hashes_match_http_provenance'] = package_hashes == http['implementation_files']
    checks['executed_verifier_matches_snapshot'] = http['verifier_sha256'] == digest(run / 'implementation/scripts/verify_upload_http.py')
    stage = read(run / 'http/pipeline-evidence.json')
    report['stage_inventory'] = inventory(job, stage['artifacts'])
    checks['stage_artifacts_bound'] = not report['stage_inventory']['errors']
    checks['stage_gate_bound_to_receipt'] = receipt['job']['pipeline_evidence'] == stage
    checks['full_scientific_stage_evidence_passed'] = (stage.get('passed') is True
        and stage.get('full_pipeline_observed') is True and stage.get('scientific_decision_expected') is True
        and stage.get('errors') == [])
    checks['all_runner_crosslinks_passed'] = all(value is True for value in receipt['job']['checks'].values())
    report['runner_crosslinks'] = receipt['job']['checks']
    report['outcome'] = {'status': final['status'], 'reason_code': final.get('reason_code'),
        'runner_passed': receipt['passed'], 'http_checks_passed': http['http_checks_passed'],
        'strict_expectation_matched': http.get('expectation_matched'),
        'pipeline_evidence_passed': http['pipeline_evidence_passed'],
        'finite_search_verified': stage.get('finite_search_verified'),
        'supported_decision': receipt['supported_decision'],
        'accepted_tiers': receipt['supported_localization_at_m'],
        'candidate_count': len(final.get('candidates', [])), 'elapsed_s': receipt['elapsed_s']}
    checks['unsupported_status_has_no_accepted_tier'] = (final['status'] == 'succeeded'
        or (receipt['supported_decision'] is False and receipt['passed'] is False
            and not any(receipt['supported_localization_at_m'].values())))
    report['finite_retention'] = audit_retention(job, final, checks)
    report['withheld_truth_comparison'] = audit_truth(run, receipt, final, checks)

def audit_truth(run, receipt, final, checks):
    from pyproj import Geod
    labels = read(run / 'evaluation/truth/labels.json')
    mapping = read(run / 'evaluation/flight-id-mapping.json')['original_to_opaque']
    evaluated = read(run / 'candidate-evaluations.json')
    expected_flights = {mapping[event['flight_id']] for event in labels['events']}
    parse = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))
    reference = parse(labels['recording_start_utc'])
    window = receipt['normal_request']['time_window']
    start, end = parse(window['start_utc']), parse(window['end_utc'])
    errors, distances, correct = [], [], []
    if len(evaluated) != len(final['candidates']):
        errors.append('candidate_count')
    for index, (candidate, item) in enumerate(zip(final['candidates'], evaluated), 1):
        distance = abs(Geod(ellps='WGS84').inv(labels['location'][1], labels['location'][0], candidate['lon'], candidate['lat'])[2])
        flights_correct = set(candidate['flight_ids']) == expected_flights
        clock = parse(candidate['recording_start_utc'])
        distances.append(distance)
        correct.append(flights_correct)
        if (not math.isclose(item['error_m'],distance,rel_tol=1e-12,abs_tol=1e-8)
                or item['full_true_flight_set_correct'] is not flights_correct
                or item['clock']['clock_error_s'] != (clock-reference).total_seconds()
                or item['clock']['within_request_window'] is not (start <= clock <= end)
                or item['within_m'] != {str(limit): distance <= limit for limit in (100,500,1000)}):
            errors.append(index)
    counts = {str(limit): {'all_candidates': sum(distance <= limit for distance in distances),
        'correct_full_flight_set': sum(distance <= limit and flight for distance,flight in zip(distances,correct))}
        for limit in (100,500,1000)}
    checks['all_candidate_errors_flight_sets_clocks_recomputed'] = not errors
    checks['diagnostic_threshold_counts_recomputed'] = counts == receipt['threshold_counts']
    checks['leading_prediction_error_recomputed'] = math.isclose(distances[0],receipt['leading_prediction_error_m'],rel_tol=1e-12,abs_tol=1e-8)
    return {'reference_sha256': digest(run / 'evaluation/truth/labels.json'),
        'candidate_count': len(distances), 'leading_error_m': distances[0],
        'leading_full_flight_set_correct': correct[0], 'threshold_counts': counts,
        'mismatches': errors, 'limitations': ['Candidate rows are correlated hypotheses from one scene, not independent accuracy trials.']}

def audit_retention(job, final, checks):
    search = read(job / 'search/search-report.json')
    refined = read(job / 'refined-candidates.json')
    decision = read(job / 'decision.json')
    finite = search['finite_search_evidence']
    path = job / 'search/retention.sqlite'
    before = digest(path)
    retained_ids = {row['mode_id'] for row in search['ranked']}
    with sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True) as database:
        checks['ledger_integrity'] = database.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        checks['ledger_run_identity'] = database.execute('SELECT identity,score_kind FROM run').fetchall() == [(search['run_hash'], finite['score_kind'])]
        all_modes = database.execute('SELECT mode_id,MAX(score),MIN(groups_count),MAX(groups_count) FROM records GROUP BY mode_id ORDER BY MAX(score) DESC').fetchall()
        stage_counts = database.execute("SELECT substr(name,1,instr(name,':')-1),COUNT(*) FROM stages GROUP BY 1").fetchall()
        record_count = database.execute('SELECT COUNT(*) FROM records').fetchone()[0]
        seed_errors = []
        for identity, encoded in database.execute('SELECT DISTINCT mode_id,seed FROM records'):
            seed = json.loads(encoded)
            calculated = 'mode-'+hashlib.sha256(json.dumps(seed,sort_keys=True,allow_nan=False).encode()).hexdigest()
            if identity != calculated:
                seed_errors.append(identity)
    checks['ledger_read_only_bytes_unchanged'] = digest(path) == before
    checks['ledger_exact_seed_identities'] = not seed_errors
    checks['ledger_group_counts_stable'] = all(row[2] == row[3] and 1 <= row[2] <= finite['max_event_groups'] for row in all_modes)
    drops = [row for row in all_modes if row[0] not in retained_ids]
    maximum_dropped = max((row[1] for row in drops), default=None)
    checks['ledger_distinct_counts'] = len(all_modes) == finite['evaluated_modes'] and len(drops) == finite['discarded_count']
    unknown = finite['unclassified_score_candidates']
    checks['ledger_bound_matches_all_dropped_modes'] = finite['best_discarded_score'] == (None if unknown else maximum_dropped)
    checks['unknown_trials_preclude_finite_completeness'] = not unknown or finite['complete'] is False
    checks['original_retained_set_present'] = retained_ids <= {row[0] for row in all_modes}
    trials = {'scheduled': 0, 'evaluated': 0, 'rejected': 0, 'unknown': 0, 'unknown_reasons': {}}
    trial_errors = []
    for row in search['ranked']:
        assessment = row.get('scoring_assessment', {})
        values = [assessment.get(key+'_trials') for key in ('scheduled', 'evaluated', 'rejected', 'unknown')]
        valid = all(type(value) is int and value >= 0 for value in values)
        if not valid or values[0] != values[1]+values[3] or values[2] > values[1]:
            trial_errors.append(row['mode_id'])
            continue
        for key, value in zip(('scheduled', 'evaluated', 'rejected', 'unknown'), values):
            trials[key] += value
        for reason, count in assessment.get('unknown_reasons', {}).items():
            trials['unknown_reasons'][reason] = trials['unknown_reasons'].get(reason, 0)+count
        if assessment.get('complete') is not (values[0] > 0 and values[3] == 0):
            trial_errors.append(row['mode_id'])
    checks['retained_clock_trial_accounting'] = not trial_errors
    candidates = final['candidates']
    best = candidates[0]
    threshold = .2 if best['score_kind'] == 'matched_group_support_minus_normalized_residual' else .5
    gap = None if maximum_dropped is None else (best['score']-maximum_dropped)/finite['max_event_groups']
    tied = lambda value: value <= threshold or math.isclose(value,threshold,rel_tol=1e-12,abs_tol=1e-12)
    competitive_drops = [row for row in drops if tied((best['score']-row[1])/finite['max_event_groups'])]
    checks['competitive_dropped_modes_cannot_pass'] = not competitive_drops or final['status'] != 'succeeded'
    checks['unknown_modes_cannot_pass'] = not unknown or final['status'] != 'succeeded'
    envelope = audit_envelope(final, refined, decision, threshold, checks)
    return {'ledger_sha256': before, 'record_occurrences': record_count, 'stage_counts': dict(stage_counts),
        'unique_evaluated_modes': len(all_modes), 'retained_mode_count': len(retained_ids),
        'dropped_mode_count': len(drops), 'maximum_observed_dropped_score': maximum_dropped,
        'published_dropped_upper_bound': finite['best_discarded_score'], 'dropped_gap_per_maximum_group': gap,
        'unchanged_competition_threshold': threshold, 'competitive_dropped_mode_count': len(competitive_drops),
        'top_dropped_modes': [{'mode_id': row[0], 'score': row[1], 'event_groups': row[2]} for row in drops[:5]],
        'unclassified_score_candidates': unknown, 'recorded_complete': finite['complete'],
        'retained_trial_totals': trials, 'retained_trial_errors': trial_errors, 'envelope': envelope}

def audit_envelope(final, refined, decision, threshold, checks):
    from pyproj import Geod
    candidates, rows = final['candidates'], refined['ranked']
    best = candidates[0]
    lookup = {event['event_id']: event for event in final['events']}
    groups = lambda candidate: {lookup[key].get('harmonic_group_id', key) for key in candidate['event_ids']}
    associations = lambda candidate: dict(zip(candidate['event_ids'], candidate['flight_ids']))
    best_groups, best_association = groups(best), associations(best)
    near, mismatched = [], []
    for index, candidate in enumerate(candidates):
        gap = (best['score']-candidate['score'])/max(len(best_groups),len(groups(candidate)))
        if gap <= threshold or math.isclose(gap,threshold,rel_tol=1e-12,abs_tol=1e-12):
            distance = abs(Geod(ellps='WGS84').inv(best['lon'],best['lat'],candidate['lon'],candidate['lat'])[2])
            sensitivity = rows[index].get('sensitivity', {})
            radius = sensitivity.get('radius_m',0) if sensitivity.get('complete') and not sensitivity.get('boundary_limited') else 0
            near.append({'index': index, 'distance_m': distance, 'tested_radius_m': radius})
            if associations(candidate) != best_association:
                mismatched.append(index)
    checks['competitive_association_changes_cannot_pass'] = not mismatched or final['status'] != 'succeeded'
    published = decision.get('diagnostics',{}).get('finite_envelope')
    calculated = max(row['distance_m']+row['tested_radius_m'] for row in near)
    if published is not None:
        checks['finite_union_radius_recomputed'] = math.isclose(calculated,published['radius_m'],rel_tol=1e-12,abs_tol=1e-8)
        checks['finite_union_members_recomputed'] = published['included_candidate_indices'] == [row['index'] for row in near]
        checks['finite_union_within_target_if_successful'] = calculated <= 1000 or final['status'] != 'succeeded'
    checks['supported_finite_result_has_union'] = final['status'] != 'succeeded' or published is not None
    return {'near_tied_candidates': len(near), 'different_association_indices': mismatched,
        'independent_point_plus_reported_profile_union_m': calculated, 'published_union': published}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--equivalent-commit')
    parser.add_argument('--expected-tree')
    args = parser.parse_args()
    run, output = args.run.resolve(), args.output.resolve()
    if output.is_relative_to(run) or output.exists():
        raise ValueError('Output must be a new file outside the immutable run')
    answer = audit(run, args.repository.resolve(), args.equivalent_commit, args.expected_tree)
    output.write_text(json.dumps(answer, indent=2, sort_keys=True, allow_nan=False)+'\n')
    print(json.dumps({'output': str(output), 'sha256': digest(output), 'audit_passed': answer['audit_passed'],
        'failed_checks': [key for key, passed in answer['checks'].items() if not passed], 'outcome': answer.get('outcome')}))
