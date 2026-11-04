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
