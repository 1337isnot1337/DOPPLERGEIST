"""Contract checks on complete observed real-media runs, without audio generation."""
import gzip
import json
from pathlib import Path

import pytest

from dopplergeist.contracts import validate_event

ROOT=Path(__file__).parents[1]/'benchmarks/acoustic-episodes-349'


@pytest.fixture(scope='module')
def observations():
    manifest=json.loads((ROOT/'manifest.json').read_text())
    with gzip.open(ROOT/'observations.jsonl.gz','rt') as stream:
        rows=[json.loads(line) for line in stream]
    assert {r['case_id'] for r in rows}=={c['id'] for c in manifest['cases']}
    return manifest,rows


def test_complete_real_case_selection_and_input_identity(observations):
    manifest,rows=observations
    assert len(rows)==32
    lookup={c['id']:c for c in manifest['cases']}
    for row in rows:
        for name in ['baseline','new','wide']:
            data=row[name]
            if data is None:
                assert name=='wide' and row['case_id']=='whole-reference'
                continue
            assert data['source_sha256']==lookup[row['case_id']]['sha256']
            assert data.get('status','complete')=='complete'
    assert len({r['new']['code']['implementation_sha256'] for r in rows})==1


def test_canonical_membership_preserves_all_measured_children(observations):
    for row in observations[1]:
        for data in [row['new'],row['wide']]:
            if data is None:
                continue
            events={e['event_id']:validate_event(e) for e in data['events']}
            assert len(events)==data['counts']['measured_child_tracks']==data['ridge_count']
            assert len(data['episodes'])==data['counts']['canonical_proposals']
            members=[]
            for episode in data['episodes']:
                assert episode['physical_motion_confirmed'] is False
                assert episode['physical_source_multiplicity']=='unresolved'
                assert {c['ridge_id'] for c in episode['children']}==set(episode['child_ridge_ids'])
                for child in episode['children']:
                    event=events[child['ridge_id']]
                    assert event['harmonic_group_id']==episode['proposal_id']
                    assert child['frequency_scale']>0 and child['raw_track_ids']
                    assert len(child['amplitude_db'])==len(event['ridge'])
                    members.append(child['ridge_id'])
                if sum(len(events[c]['ridge']) for c in episode['child_ridge_ids'])<10:
                    assert not episode['matching_eligible']
            assert len(members)==len(set(members))==len(events)
            assert set(members)==set(events)


def test_observed_gaps_and_resource_limits_are_explicit(observations):
    for row in observations[1]:
        for data in [row['new'],row['wide']]:
            if data is None:
                continue
            settings=data['settings'];counts=data['counts']
            assert counts['provisional_paths']<=settings['max_candidates']
            assert counts['provisional_observations']<=settings['max_measurements']
            assert data['association_pairs']<=settings['max_associations']
            assert len(data['reconciliation_decisions'])<=settings['max_diagnostic_traces']
            assert data['rejections']['traces']==[]
            events={e['event_id']:e for e in data['events']}
            for episode in data['episodes']:
                cells=episode['observed_intervals_s']
                assert sum(b-a for a,b in cells)==pytest.approx(episode['observed_duration_s'])
                assert episode['gaps_s']==[[a[1],b[0]] for a,b in zip(cells,cells[1:])]
                assert len(episode['children'])<=settings['max_episode_components']
                for child in episode['children']:
                    for point in events[child['ridge_id']]['ridge']:
                        assert not any(a<point['time_s']<b for a,b in episode['gaps_s'])
            assert data['coverage']['analyzed_hz'][1]<=data['coverage']['usable_upper_hz']
            assert not data['coverage']['exhaustive_outside_analyzed_range']
