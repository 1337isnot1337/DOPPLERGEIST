"""Association regressions using unchanged observations/PCM from real recordings.

Splitting and reordering measured tracks exercise bookkeeping, not a generated
signal. These assertions do not establish physical source identity or independence.
"""
import base64
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from dopplergeist.episode_discovery import DiscoverySettings, _spectrum, discover_events
from dopplergeist.episodes import (
    Associations, DiscoveryError, Ridge, deduplicate, forecast, identifier,
    motion, reconcile, stitch, support,
)
from dopplergeist.intake import IntakeRecording

FIXTURES = Path(__file__).parent / 'fixtures'


def recorded_lost():
    data = json.loads((FIXTURES / 'real_lost_episode_ridges.json').read_text())
    return {e['event_id']: np.array([[p['time_s'], p['frequency_hz'], p['weight']]
                                  for p in e['ridge']]) for e in data['events']}


def recorded_short():
    data = json.loads((FIXTURES / 'real_short_episode_ridges.json').read_text())
    return [Ridge(np.array(t['points']), (t['event_id'],)) for t in data['tracks']]


def test_real_faint_fragments_stitch_without_inventing_support():
    points = recorded_lost()['event-0009']
    settings = DiscoverySettings()
    fragments = [Ridge(p, (str(i),)) for i, p in enumerate(np.array_split(points, 3))]
    work = Associations(settings)
    joined = stitch(fragments, settings, work)
    assert len(joined) == 1
    np.testing.assert_array_equal(joined[0].points, points)
    cells, observed, _ = support(points, settings)
    assert observed == 11.5  # Actual 23 observed half-second cells.
    assert cells[-1][1] - cells[0][0] == 15.0
    assert observed < cells[-1][1] - cells[0][0]
    assert work.decision_counts['stitch_sweeps'] <= 2
    assert work.refits <= work.decision_counts['stitch_candidate_pairs'] * 2


def test_real_fragment_selection_is_order_invariant():
    fragments = [Ridge(p, (f'{name}-{i}',)) for name, points in recorded_lost().items()
                 for i, p in enumerate(np.array_split(points, 3))]
    settings = DiscoverySettings()
    def result(items):
        work = Associations(settings)
        return [(identifier('', r.points), r.origins) for r in stitch(items, settings, work)]
    assert result(fragments) == result(fragments[::-1])
    assert result(fragments) == result(fragments[::2] + fragments[1::2])


def test_shared_observation_index_does_not_merge_distinct_measured_tracks():
    tracks = recorded_short()
    settings = DiscoverySettings()
    work = Associations(settings)
    result = deduplicate(tracks + tracks[::-1], settings, work)
    assert len({identifier('', r.points) for r in result}) == len(result)
    # The index scores candidates sharing peaks, rather than all overlapping pairs.
    assert work.count < len(tracks) ** 2
    def group(items):
        groups = reconcile(items, settings, Associations(settings))
        return sorted(tuple(sorted(identifier('', r.points) for r in g[0])) for g in groups)
    assert group(result) == group(result[::-1])


def test_correlated_profiles_do_not_double_observed_time():
    points = recorded_short()[0].points
    settings = DiscoverySettings()
    cells, observed, independent = support(points, settings)
    doubled = np.concatenate((points, points))
    assert support(doubled, settings) == (cells, observed, independent)
    metrics, _ = motion(points, settings)
    assert metrics['observed_duration_s'] == observed
    # Every checked transition uses the same forecast in linking/continuity.
    errors = [abs(points[i, 1] - forecast(points[:i], points[i, 0], settings,
                                       next_sigma=points[i, 4])[0]) /
              forecast(points[:i], points[i, 0], settings, next_sigma=points[i, 4])[1]
              for i in range(2, len(points)) if points[i, 0]-points[i-1, 0] <= settings.max_gap_s]
    assert metrics['prediction_error_q95'] == pytest.approx(np.quantile(errors, .95))


def test_wider_band_preserves_lower_band_normalization_on_recorded_pcm():
    data = json.loads((FIXTURES / 'real_discovery_normalization.json').read_text())
    samples = np.frombuffer(base64.b64decode(data['excerpts'][0]['pcm_f32le_base64']), dtype='<f4')
    # Identical decoded samples, widening only the requested upper limit.
    narrow = _spectrum(samples, 4000, 0., DiscoverySettings(max_frequency_hz=400.), fixed_bands=True)
    wider = _spectrum(samples, 4000, 0., DiscoverySettings(max_frequency_hz=1600.), fixed_bands=True)
    common = (narrow.frequency >= 40) & (narrow.frequency < 400)
    other = (wider.frequency >= 40) & (wider.frequency < 400)
    np.testing.assert_array_equal(narrow.contrast[common], wider.contrast[other])


def test_real_pcm_budget_failure_is_not_a_negative_result(tmp_path):
    data = json.loads((FIXTURES / 'real_discovery_normalization.json').read_text())
    raw = base64.b64decode(data['excerpts'][0]['pcm_f32le_base64'])
    path = tmp_path / 'recording.f32'
    path.write_bytes(raw)
    recording = IntakeRecording(path, dict(sample_rate_hz=4000, duration_s=len(raw)/16000,
                                          source_sha256=data['source_sha256']), {})
    with pytest.raises(DiscoveryError, match='Spectrum needs'):
        discover_events(recording, settings=replace(DiscoverySettings(), max_spectral_cells=10),
                        output_dir=tmp_path/'result', plot_summary=False)
    artifact = json.loads((tmp_path/'result/discovery.json').read_text())
    assert artifact['status'] == 'failed'
    assert artifact['failure']['code'] == 'spectral_budget_exceeded'
    assert artifact['events'] == []


def test_deduplication_preserves_the_valid_low_frequency_alternative():
    data = json.loads((FIXTURES / 'real_episode_conflicts.json').read_text())['reference']
    good, conflicting = np.array(data['good']), np.array(data['conflicting'])
    settings = DiscoverySettings()
    assert not motion(good, settings)[1]
    work = Associations(settings)
    result = deduplicate([Ridge(good, ('good',)), Ridge(conflicting, ('conflicting',))], settings, work)
    assert identifier('', good) in {identifier('', r.points) for r in result}
    assert len(result) == 2
    assert work.decision_counts['duplicate_unresolved_interleaving'] == 1


def test_observed_pitch_step_is_not_distributed_motion():
    data = json.loads((FIXTURES / 'real_episode_conflicts.json').read_text())['step']
    metrics, reasons = motion(np.array(data['points']), DiscoverySettings())
    assert metrics['resolved_regional_motion_fraction'] < 2/3
    assert 'motion_concentrated_or_unresolved' in {r['reason'] for r in reasons}


def test_corrupted_real_audio_container_is_an_intake_failure(tmp_path):
    import soundfile as sf
    from dopplergeist.intake import AudioIntakeError, intake_recording
    data = json.loads((FIXTURES / 'real_discovery_normalization.json').read_text())
    samples = np.frombuffer(base64.b64decode(data['excerpts'][0]['pcm_f32le_base64']), dtype='<f4')
    audio = tmp_path/'recorded.wav'
    sf.write(audio, samples, 4000, subtype='FLOAT')
    # Damage the container of actual recorded PCM; no test signal is generated.
    corrupt = tmp_path/'truncated.wav'
    corrupt.write_bytes(audio.read_bytes()[:20])
    with pytest.raises(AudioIntakeError) as caught:
        intake_recording(corrupt, tmp_path/'intake')
    assert caught.value.code == 'invalid_media'


def test_prediction_cache_preserves_every_recorded_raw_path():
    import gzip
    from dopplergeist.episode_discovery import _paths
    data = json.loads((FIXTURES/'real_discovery_normalization.json').read_text())
    samples = np.frombuffer(base64.b64decode(data['excerpts'][0]['pcm_f32le_base64']), dtype='<f4')
    with gzip.open(FIXTURES/'real_uncached_paths.json.gz','rt') as stream:
        recorded = json.load(stream)
    assert data['source_sha256'] == recorded['source_sha256']
    for profile in recorded['profiles']:
        settings = DiscoverySettings(**{k: profile[k] for k in ('window_s','hop_s','max_peaks_per_frame')})
        actual = _paths(_spectrum(samples,4000,0.,settings,fixed_bands=True),settings)
        assert len(actual) == len(profile['paths'])
        for path, expected in zip(actual,profile['paths']):
            actual_points=np.asarray(path);expected_points=np.asarray(expected)
            np.testing.assert_array_equal(actual_points[:,[0,6,7]],expected_points[:,[0,6,7]])
            # FFT/log-power/peak-width rounding differs across numerical stacks.
            # Preserve path topology and timing exactly; frequency tolerance is
            # far below the minimum half-Hz spectral bin in this real fixture.
            np.testing.assert_allclose(actual_points[:,1],expected_points[:,1],rtol=1e-7,atol=1e-4)
            np.testing.assert_allclose(actual_points[:,[2,3,4,5]],expected_points[:,[2,3,4,5]],rtol=1e-5,atol=1e-4)


def test_compiled_prominence_is_exact_on_recorded_spectral_peaks():
    from scipy import signal
    from dopplergeist.episode_discovery import _peak_local_prominence
    data = json.loads((FIXTURES/'real_discovery_normalization.json').read_text())
    samples = np.frombuffer(base64.b64decode(data['excerpts'][0]['pcm_f32le_base64']), dtype='<f4')
    for window, hop in ((2.0, .5), (.5, .125)):
        settings = DiscoverySettings(window_s=window, hop_s=hop)
        spec = _spectrum(samples, 4000, 0., settings, fixed_bands=True)
        df = float(spec.frequency[1]-spec.frequency[0])
        for dtype in (np.float32, np.float64):
            db = spec.db.astype(dtype)
            for column in sorted({0, len(spec.time)//2, len(spec.time)-1}):
                peaks, _ = signal.find_peaks(db[:, column], distance=2)
                for peak in peaks:
                    radius = max(4, round(max(20., min(80., .04*spec.frequency[peak]))/df))
                    neighbours = np.r_[max(0,peak-radius):max(0,peak-3),
                                       min(len(spec.frequency),peak+4):min(len(spec.frequency),peak+radius+1)]
                    expected = float(db[peak,column]-np.median(db[neighbours,column])) if len(neighbours) else 0.
                    actual = _peak_local_prominence(db[:, column], int(peak), radius)
                    assert np.float64(actual).tobytes() == np.float64(expected).tobytes()


def test_recorded_context_reveals_reversals_outside_legacy_crop():
    import gzip
    with gzip.open(FIXTURES/'real_modulated_context.json.gz','rt') as stream:
        data = json.load(stream)
    settings = DiscoverySettings()
    cropped, crop_reasons = motion(np.array(data['legacy_crop']),settings)
    full, full_reasons = motion(np.array(data['full']),settings)
    assert not crop_reasons
    assert cropped['sustained_turns'] == 0
    assert full['sustained_turns'] == 2
    assert 'repeated_modulation' in {r['reason'] for r in full_reasons}


def test_recorded_late_union_cannot_erase_supported_parent():
    import gzip
    from dopplergeist.episode_discovery import _episode_evidence
    with gzip.open(FIXTURES/'real_group_extension.json.gz','rt') as stream:
        data=json.load(stream)
    settings=DiscoverySettings()
    def accepted(group):
        members=[Ridge(np.array(points),(str(i),)) for i,points in enumerate(group['points'])]
        metrics=[motion(r.points,settings)[0] for r in members]
        evidence=_episode_evidence(members,group['scales'],settings,metrics)
        return not evidence['rejections'] and (evidence['long'] or evidence['brief'])
    assert accepted(data['parent'])
    assert not accepted(data['union'])


def test_reconciliation_obeys_group_acceptance_guard():
    tracks=recorded_short();settings=DiscoverySettings();work=Associations(settings)
    ordinary=reconcile(tracks,settings,Associations(settings))
    assert len(ordinary)<len(tracks)  # Actual compatible recorded components.
    guarded=reconcile(tracks,settings,work,accept_merge=lambda *groups:False)
    assert len(guarded)==len(tracks)
    assert work.decision_counts['rejected_episode_extension']>0


def test_final_real_recording_catalog_preserves_contract_and_bounds():
    import gzip
    from dopplergeist.contracts import validate_event
    root=Path(__file__).parents[1]/'benchmarks'
    manifest=json.loads((root/'acoustic-episodes-349/manifest.json').read_text())
    expected={c['id']:c['sha256'] for c in manifest['cases']}
    package=root/'acoustic-episode-repair-20261104'
    with gzip.open(package/'observations.jsonl.gz','rt') as stream:
        rows=[json.loads(line) for line in stream]
    assert {r['case_id'] for r in rows}==set(expected)
    with gzip.open(package/'wide-observations.jsonl.gz','rt') as stream:
        wider=[json.loads(line) for line in stream]
    assert len(wider)==31
    identities=set()
    for cid,data in [(r['case_id'],r['repaired']) for r in rows]+[(r['case_id'],r['wide']) for r in wider]:
        assert data['status']=='complete'
        assert data['source_sha256']==expected[cid]
        identities.add(data['code']['implementation_sha256'])
        events={e['event_id']:validate_event(e) for e in data['events']}
        members=[rid for episode in data['episodes'] for rid in episode['child_ridge_ids']]
        assert len(members)==len(set(members))==len(events)
        assert set(members)==set(events)
        assert data['counts']['canonical_proposals']==len(data['episodes'])
        assert data['counts']['measured_child_tracks']==len(events)
        assert data['association_pairs']<=data['settings']['max_associations']
        assert data['joint_refits']<=data['settings']['max_joint_refits']
        assert len(data['protected_group_extensions'])<=20
        for episode in data['episodes']:
            assert episode['physical_motion_confirmed'] is False
            assert episode['physical_source_multiplicity']=='unresolved'
            cells=episode['observed_intervals_s']
            assert sum(b-a for a,b in cells)==pytest.approx(episode['observed_duration_s'])
            assert episode['gaps_s']==[[a[1],b[0]] for a,b in zip(cells,cells[1:])]
            for child in episode['children']:
                n=len(events[child['ridge_id']]['ridge'])
                assert len(child['frequency_uncertainties_hz'])==len(child['observation_hops_s'])==len(child['observation_windows_s'])==n
    assert len(identities)==1
