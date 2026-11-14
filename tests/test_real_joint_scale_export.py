"""Whole-group scale export on actual complete pressure-recording observations."""
from collections import defaultdict
import copy
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from dopplergeist import advanced_discovery
from dopplergeist import automatic, matching
from dopplergeist.contracts import validate_event
from dopplergeist.discovery import _export_group_frequency_scales, discover_events
from dopplergeist.intake import intake_recording
from dopplergeist.matching import prepare_events, UnreconciledHarmonicGroup


FIXTURES = Path(__file__).parent / 'fixtures'
RECORDED = json.loads(gzip.decompress((FIXTURES / 'real_utah_joint_groups.json.gz').read_bytes()))


def groups(events):
    result = defaultdict(list)
    for event in events:
        result[event.get('harmonic_group_id') or event['event_id']].append(event)
    return result


@pytest.mark.parametrize('case', RECORDED['channels'], ids=lambda case: case['channel'])
def test_only_complete_compatible_recorded_groups_gain_scales(case):
    original = copy.deepcopy(case['events'])
    for members in groups(original).values():
        with pytest.raises(UnreconciledHarmonicGroup):
            prepare_events(members)
    exported, evidence = _export_group_frequency_scales(case['events'])
    assert case['events'] == original
    assert len(exported) == len(original)
    expected = set(case['full_joint_compatible_groups'])
    assert {key for key, row in evidence.items() if row['applied']} == expected
    for before, after in zip(original, exported):
        validate_event(after)
        restored = copy.deepcopy(after)
        if after['harmonic_group_id'] in expected:
            assert restored['quality'].pop('episode_frequency_scale') > 0
        assert restored == before
    for key, members in groups(exported).items():
        if key in expected:
            prepared, measured = prepare_events(members)
            assert len(prepared) == len(measured) == 1
            assert prepared[0]['event_ids'] == [event['event_id'] for event in members]
            assert len(measured[0][0].time) == sum(len(event['ridge']) for event in members)
            assert {row['event_id'] for row in evidence[key]['joint_fit']['track_residuals']} == {
                event['event_id'] for event in members}
        else:
            assert evidence[key]['reason'] == 'incompatible_joint_fit'
            with pytest.raises(UnreconciledHarmonicGroup):
                prepare_events(members)
    # Unresolved whole groups still stop the unchanged full-recording consumer.
    with pytest.raises(UnreconciledHarmonicGroup):
        prepare_events(exported)


def test_supported_actual_group_and_short_recorded_ridge_are_unchanged():
    for filename in ['real_livermore_supported_ridge.json', 'real_livermore_short_ridge.json']:
        original = json.loads((FIXTURES / filename).read_text())['events']
        exported, evidence = _export_group_frequency_scales(original)
        assert exported == original and evidence == {}
    original = json.loads((FIXTURES / 'real_livermore_supported_ridge.json').read_text())['events']
    before, before_measurements = prepare_events(original)
    after, after_measurements = prepare_events(_export_group_frequency_scales(original)[0])
    assert before == after
    np.testing.assert_array_equal(before_measurements[0][0].time, after_measurements[0][0].time)
    for left, right in zip(before_measurements[0][1:3], after_measurements[0][1:3]):
        np.testing.assert_array_equal(left, right)


def test_existing_measured_producer_scales_are_not_overwritten():
    case = RECORDED['channels'][1]
    exported, _ = _export_group_frequency_scales(case['events'])
    key = case['full_joint_compatible_groups'][0]
    members = groups(exported)[key]
    repeated, evidence = _export_group_frequency_scales(members)
    assert repeated == members and evidence == {}


def test_existing_recorded_multiband_episode_keeps_all_prepared_observations():
    original = json.loads((FIXTURES / 'real_episode_children.json').read_text())['events']
    assert len(original) == 6
    exported, evidence = _export_group_frequency_scales(original)
    assert exported == original and evidence == {}
    before, before_measurements = prepare_events(original)
    after, after_measurements = prepare_events(exported)
    assert len(before) == len(after) == 1
    assert before == after
    assert len(after[0]['event_ids']) == 6
    np.testing.assert_array_equal(before_measurements[0][0].time, after_measurements[0][0].time)
    for left, right in zip(before_measurements[0][1:3], after_measurements[0][1:3]):
        np.testing.assert_array_equal(left, right)


def test_subset_only_fit_cannot_annotate_a_whole_recorded_group(monkeypatch):
    case = RECORDED['channels'][1]
    members = groups(case['events'])[case['full_joint_compatible_groups'][0]]
    measured_fit = advanced_discovery.joint_pass_evidence(members)
    assert measured_fit['compatible']
    measured_fit['track_residuals'] = measured_fit['track_residuals'][:-1]
    # A truncated real fit is a software fault control, never positive evidence.
    monkeypatch.setattr(advanced_discovery, 'joint_pass_evidence', lambda events: measured_fit)
    exported, evidence = _export_group_frequency_scales(members)
    assert exported == members
    assert not next(iter(evidence.values()))['applied']
    assert next(iter(evidence.values()))['reason'] == 'incomplete_or_invalid_joint_scales'


def test_real_audio_resume_rejects_a_changed_preparation_contract(tmp_path, monkeypatch):
    source = tmp_path / 'actual-lowrate.wav'
    source.write_bytes(gzip.decompress((FIXTURES / 'real_lowrate_piston_1000hz.wav.gz').read_bytes()))
    output = tmp_path / 'actual-checkpoint'
    recording = intake_recording(source, output / 'intake')
    events = discover_events(recording, output_dir=output / 'discovery',
        plot_summary=False, plot_event_details=False, event_audio=False)
    assert events
    request = {'schema_version': 1, 'audio_path': str(source), 'search': {'coverage': 'conus'}}
    automatic._save_audio_checkpoint(output, request, {})
    _, resumed = automatic._load_audio_checkpoint(output, request, {})
    assert resumed == events
    saved = (output / 'resume.json').read_bytes()
    preparation_path = Path(matching.__file__).resolve()
    changed = hashlib.sha256(preparation_path.read_bytes() + b'\n# preparation contract changed\n').hexdigest()
    original_digest = automatic._digest

    def changed_preparation_digest(path):
        return changed if Path(path).resolve() == preparation_path else original_digest(path)

    # Change only the preparation dependency identity, leaving all real samples,
    # measured ridges, request and checkpoint files untouched.
    monkeypatch.setattr(automatic, '_digest', changed_preparation_digest)
    with pytest.raises(ValueError, match='detector changed'):
        automatic._load_audio_checkpoint(output, request, {})
    assert (output / 'resume.json').read_bytes() == saved
