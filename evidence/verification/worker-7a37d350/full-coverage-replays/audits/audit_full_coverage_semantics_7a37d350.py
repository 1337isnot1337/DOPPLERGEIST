"""Read-only semantic audit; no project evaluation/decision function is imported."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json, math
from pyproj import Geod


def read(path):
    return json.loads(path.read_text())


def record(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def utc(value):
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('UTC timestamp must contain a timezone')
    return moment.astimezone(timezone.utc)


def audit(root, output):
    if output.exists():
        raise ValueError('Refusing to replace an earlier audit')
    a = read(root / 'acceptance.json')
    h = read(root / 'http/http-verification.json')
    result = read(root / 'http/result.json')
    pipeline = read(root / 'http/pipeline-evidence.json')
    service = h['service']
    stopped = (service['shutdown_signal'] == 'SIGINT' and service['returncode'] == 0
               and service['forced_kill'] is False and a['service_and_workers_stopped'] is True)
    ordered = (utc(service['stopped_utc']) <= utc(a['analysis_stopped_utc'])
               < utc(a['evaluation_truth_load_started_utc']) <= utc(a['evaluation_truth_loaded_utc']))
    if not stopped or not ordered:
        raise ValueError('Shutdown-before-truth order was not established')
    job = root / 'http/jobs' / h['job_id']
    if job.resolve().parent != (root / 'http/jobs').resolve():
        raise ValueError('Unexpected job path')
    decision = read(job / 'decision.json')
    refinement = read(job / 'refined-candidates.json')
    labels = read(root / 'evaluation/truth/labels.json')
    mapping = read(root / 'evaluation/flight-id-mapping.json')['original_to_opaque']
    lookup = {event['event_id']: event for event in result['events']}
    windows = {mapping[event['flight_id']]: (event['start_s'], event['end_s']) for event in labels['events']}
    geod = Geod(ellps='WGS84')
    differences, candidate_reports = [], []
    # The frozen runner declares half the discovery window as its edge tolerance.
    tolerance = a['job']['discovery_settings']['window_s'] / 2
    for index, (candidate, saved) in enumerate(zip(result['candidates'], a['candidate_evaluations'])):
        groups = {}
        valid = len(candidate['event_ids']) == len(candidate['flight_ids']) and len(set(candidate['event_ids'])) == len(candidate['event_ids'])
        for event_id, flight in zip(candidate['event_ids'], candidate['flight_ids']):
            event = lookup[event_id]
            key = event.get('harmonic_group_id') or event_id
            group = groups.setdefault(key, {'flight_id': flight, 'times': set()})
            valid &= group['flight_id'] == flight
            group['times'].update(float(point['time_s']) for point in event['ridge']
                                  if type(point.get('time_s')) in (int, float) and math.isfinite(point['time_s']))
        timing, compatible_flights = [], set()
        for key, group in groups.items():
            times = group['times']
            fractions = {flight: sum(lo - tolerance <= t <= hi + tolerance for t in times) / len(times)
                         if times else None for flight, (lo, hi) in windows.items()}
            target = fractions.get(group['flight_id'])
            cross = {flight: value for flight, value in fractions.items() if flight != group['flight_id']}
            compatible = (len(times) >= 3 and target is not None and target >= .9
                          and all(value is not None and value < .9 for value in cross.values()))
            if compatible:
                compatible_flights.add(group['flight_id'])
            timing.append({'group_id': key, 'flight_id': group['flight_id'], 'ridge_times': len(times),
                           'target_interval_fraction': target, 'other_true_interval_fractions': cross, 'compatible': compatible})
        if index == 0:
            leading_exact_intervals = {key: {flight: sum(lo <= t <= hi for t in group['times']) / len(group['times']) for flight, (lo, hi) in windows.items()} for key, group in groups.items()}
        timing_ok = bool(groups) and valid and all(row['compatible'] for row in timing) and compatible_flights == set(windows)
        recorded_timing = saved['association_timing']
        expected_groups = {row['group_id']: row for row in timing}
        saved_groups = {row['group_id']: row for row in recorded_timing['groups']}
        if expected_groups != saved_groups or timing_ok != recorded_timing['compatible'] or len(compatible_flights) != recorded_timing['compatible_true_flyovers'] or tolerance != recorded_timing['edge_tolerance_s']:
            differences.append({'rank': index + 1, 'field': 'association_timing'})
        error = abs(geod.inv(labels['location'][1], labels['location'][0], candidate['lon'], candidate['lat'])[2])
        clock_error = (utc(candidate['recording_start_utc']) - utc(labels['recording_start_utc'])).total_seconds()
        window = a['normal_request']['time_window']
        within_clock = utc(window['start_utc']) <= utc(candidate['recording_start_utc']) <= utc(window['end_utc'])
        full_flights = set(candidate['flight_ids']) == set(windows)
        tiers = {str(limit): error <= limit for limit in (100, 500, 1000)}
        if not math.isclose(error, saved['error_m'], abs_tol=1e-9) or saved['within_m'] != tiers or saved['full_true_flight_set_correct'] != full_flights or saved['clock']['clock_error_s'] != clock_error or saved['clock']['within_request_window'] != within_clock:
            differences.append({'rank': index + 1, 'field': 'position_clock_flights_or_tiers'})
        candidate_reports.append({'rank': index + 1, 'error_m': error, 'clock_error_s': clock_error,
                                  'inside_clock_window': within_clock, 'true_flight_set': full_flights,
                                  'independent_groups': len(groups), 'association_timing_compatible': timing_ok,
                                  'groups': timing if index == 0 else None})
    best = result['candidates'][0]
    diag = decision['diagnostics']
    raw = refinement['ranked']
    event_groups = lambda row: {lookup[event_id].get('harmonic_group_id') or event_id for event_id in row['event_ids']}
    association = lambda row: dict(zip(row['event_ids'], row['flight_ids']))
    near, different_associations = [], []
    margin = diag['policy']['near_tie_support_per_group']
    for index, candidate in enumerate(result['candidates']):
        gap = (best['score'] - candidate['score']) / max(len(event_groups(best)), len(event_groups(candidate)))
        if gap <= margin or math.isclose(gap, margin, rel_tol=1e-12, abs_tol=1e-12):
            separation = abs(geod.inv(best['lon'], best['lat'], candidate['lon'], candidate['lat'])[2])
            base = raw[index].get('sensitivity', {}).get('radius_m', 0.)
            near.append({'index': index, 'separation_m': separation, 'profile_radius_m': base,
                         'required_radius_m': separation + base, 'mode_id': raw[index]['mode_id']})
            if association(candidate) != association(best):
                different_associations.append(index)
    union = max(row['required_radius_m'] for row in near)
    envelope = diag['finite_envelope']
    finite = pipeline['finite_search']
    checks = {
        'clean_stop_before_truth': stopped and ordered,
        'http_receipt_bound': a['http_verification'] == h,
        'persisted_result_matches_download': read(job / 'result.json') == result,
        'decision_matches_result': decision['status'] == result['status'] and decision['reason_code'] == result['reason_code'] and decision['candidates'] == result['candidates'],
        'all_raw_http_checks_passed': len(h['checks']) == 7 and all(value is True for value in h['checks'].values()),
        'all_job_crosschecks_passed': len(a['job']['checks']) == 18 and all(value is True for value in a['job']['checks'].values()) and not a['job']['errors'],
        'all_seven_stages_verified': pipeline['passed'] is True and pipeline['full_pipeline_observed'] is True and len(pipeline['stages_verified']) == 7 and not pipeline['errors'],
        'uninterrupted_execution': h['interrupted'] is False and h['interruption_signal'] is None and not h.get('timed_out') and not h.get('shutdown_error'),
        'predeclared_supported_success': a['expected_status'] == h['expected_status'] == result['status'] == 'succeeded' and result['reason_code'] == 'supported_by_evidence_checks' and h['expectation_matched'] is True,
        'all_candidate_semantics_recomputed': len(result['candidates']) == len(a['candidate_evaluations']) == len(candidate_reports) and not differences,
        'four_distinct_true_flyovers_supported': candidate_reports[0]['true_flight_set'] and candidate_reports[0]['independent_groups'] == 4 and candidate_reports[0]['association_timing_compatible'],
        'leading_timing_also_passes_without_edge_tolerance': all(fractions[group['flight_id']] == 1.0 and all(value == 0.0 for flight, value in fractions.items() if flight != group['flight_id']) for group in candidate_reports[0]['groups'] for fractions in [leading_exact_intervals[group['group_id']]]),
        'known_clock_exact': candidate_reports[0]['clock_error_s'] == 0 and candidate_reports[0]['inside_clock_window'] and window['start_utc'] == window['end_utc'],
        'finite_evidence_complete_without_unknowns': finite['ledger_verified'] is True and finite['complete'] is True and finite['unclassified_score_candidates'] == 0 and pipeline['finite_search_verified'] is True,
        'finite_mode_counts_reconcile': finite['evaluated_modes'] == finite['retained_modes'] + finite['discarded_count'],
        'finite_union_independently_recomputed': math.isclose(union, best['uncertainty']['radius_m'], abs_tol=1e-9) and math.isclose(union, envelope['radius_m'], abs_tol=1e-9),
        'near_tie_indices_and_modes_match': [row['index'] for row in near] == envelope['included_candidate_indices'] and sorted({row['mode_id'] for row in near}) == envelope['included_mode_ids'] and not different_associations,
        'union_within_declared_target': union <= diag['policy']['target_radius_m'],
        'uncertainty_remains_uncalibrated': best['uncertainty']['kind'] == 'sensitivity' and best['uncertainty']['method'] == 'finite_mode_and_tested_profile_union' and diag['calibration'] == 'uncalibrated' and diag['probability'] is None,
        'all_accuracy_tiers_accepted': a['supported_localization_at_m'] == {str(limit): candidate_reports[0]['error_m'] <= limit for limit in (100, 500, 1000)} and a['supported_decision'] is True and a['supported_localization_passed'] is True and a['passed'] is True,
        'all_execution_stages_exit_zero': all(stage['execution']['returncode'] == 0 for stage in a['stages']),
        'predeclared_budget_respected': a['time_budget_respected'] is True and a['total_budget_s'] == 1800 and a['elapsed_s'] < a['total_budget_s'],
        'all_declared_tiles_complete': a['job']['search']['tiles_total'] == a['job']['search']['tiles_completed'] == 4940 and a['job']['search']['unsearched_tiles'] == 0,
        'full_coverage_inventory_preserved': a['fixture_variant'] == 'full-coverage' and a['indexing']['rows'] == 26688 and a['indexing']['tracks'] == 12 and a['indexing']['all_rows_retained'] is True,
        'truth_or_manual_event_fields_absent_from_request': set(a['normal_request']) == {'schema_version', 'search', 'time_window'} and a['normal_request']['search'] == {'coverage': 'conus'},
        'source_snapshot_unchanged': a['source_snapshot_unchanged'] is True and a['implementation']['git']['status'] == '',
        'real_and_browser_claims_remain_false': all(a[field] is False for field in ('browser_verified', 'independent_real_accuracy_verified', 'live_acquisition_verified', 'real_national_coverage_verified')),
    }
    data = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(), 'audit_passed': all(checks.values()),
            'scope': 'Independent receipt, geometry, clock, all-candidate ridge-window association, and finite-union semantic audit. Full inventory and SQLite audits are separate.',
            'checks': checks, 'script': record(Path(__file__)), 'acceptance': record(root / 'acceptance.json'),
            'result': record(root / 'http/result.json'), 'decision': record(job / 'decision.json'),
            'refinement': record(job / 'refined-candidates.json'), 'truth': record(root / 'evaluation/truth/labels.json'),
            'mapping': record(root / 'evaluation/flight-id-mapping.json'), 'source_commit': a['implementation']['git']['commit'],
            'source_snapshot_sha256': a['implementation']['snapshot_sha256'], 'job_id': h['job_id'],
            'status': result['status'], 'reason_code': result['reason_code'], 'elapsed_s': a['elapsed_s'],
            'search_elapsed_s': a['job']['search']['elapsed_s'], 'service_stopped_utc': service['stopped_utc'],
            'truth_load_started_utc': a['evaluation_truth_load_started_utc'], 'recomputed_candidates': len(candidate_reports),
            'candidate_semantic_differences': differences, 'leading_candidate': candidate_reports[0], 'leading_zero_tolerance_interval_fractions': leading_exact_intervals, 'declared_edge_tolerance_s': tolerance,
            'finite_union': {'recomputed_radius_m': union, 'reported_radius_m': best['uncertainty']['radius_m'],
                             'base_profile_radius_m': raw[0]['sensitivity']['radius_m'], 'near_tied_rows': near,
                             'near_tied_mode_count': len({row['mode_id'] for row in near})},
            'finite_evidence': finite,
            'limits': ['No physical scoring trial was independently rerun by this audit.', 'Point-error tiers do not imply a 100 m uncertainty bound.',
                       'Finite union is uncalibrated and does not establish continuous-space uniqueness.', 'Exact known clock, constant synthetic terrain, and complete generated traffic remain fixture assumptions.',
                       'No independent real-recording localization claim follows from this synthetic success.']}
    output.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print(json.dumps({'audit': record(output), 'passed': data['audit_passed'], 'checks': len(checks),
                      'false_checks': [key for key, value in checks.items() if not value], 'error_m': candidate_reports[0]['error_m'],
                      'radius_m': union, 'association_groups': candidate_reports[0]['groups']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    audit(args.run_root.resolve(), args.output.resolve())
