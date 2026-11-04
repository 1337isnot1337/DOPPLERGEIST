"""Bookkeeping and mathematical properties, without audio synthesis.

Coordinate arrays here exercise association algebra, not signal detection or
empirical accuracy. Signal tests below use only the existing real PCM fixture.
"""
import base64
from dataclasses import replace
import itertools
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from dopplergeist.discovery import DiscoverySettings, _spectrum, discover_events, required_sample_rate
from dopplergeist.episodes import (Associations, DiscoveryError, Ridge, deduplicate, identifier,
                                  intervals, motion, reconcile, stitch)
from dopplergeist.intake import AudioIntakeError, intake_recording
from dopplergeist.matching import prepare_events


def coordinates(start=0, stop=20, scale=1, rising=False, envelope=True):
    t = np.arange(start, stop, .5)
    f = 200 + (2 if rising else -2) * t
    p = np.column_stack((t, scale*f, np.full(len(t), 6.)))
    if envelope:
        p = np.column_stack((p, -20 + .8*t))
    return p


def track(points, chunk='a'):
    return Ridge(points, (chunk+':'+identifier('raw-',points),))


def test_cells_count_observations_without_spanning_missing_time():
    cells=intervals([0,.5,1,10,10.5],.5)
    assert cells==[[0.,1.25],[9.75,10.75]]
    assert sum(b-a for a,b in cells)==2.25


def test_deterministic_complete_link_grouping_and_noninteger_scales():
    paths=[track(coordinates(scale=scale),str(i)) for i,scale in enumerate([1,2,3.14159])]
    s=DiscoverySettings()
    identities=[]
    for permutation in itertools.permutations(paths):
        groups=reconcile(permutation,s,Associations(s))
        assert len(groups)==1
        members,scales,orders,model=groups[0]
        assert orders is None
        assert model["checked_overlap_pairs"]==3
        assert model["worst_residual_fraction_of_limit"]<=1
        assert scales==pytest.approx([1,2,3.14159])
        identities.append([identifier('',r.points) for r in members])
    assert all(x==identities[0] for x in identities)


def test_weak_bridge_cannot_join_inconsistent_groups(monkeypatch):
    s=DiscoverySettings()
    paths=[track(coordinates(scale=k),str(k)) for k in (1,2,3)]
    from dopplergeist import episodes
    original=episodes.related
    def graph(a,b,settings):
        # Bookkeeping graph A-B-C has no joint A-C witness.
        if max(np.median(a[:,1]),np.median(b[:,1]))/min(np.median(a[:,1]),np.median(b[:,1]))>2.5:
            return None
        return original(a,b,settings)
    monkeypatch.setattr(episodes,'related',graph)
    groups=reconcile(paths,s,Associations(s))
    assert len(groups)==2
    assert sorted(len(g[0]) for g in groups)==[1,2]


def test_later_witnesses_reconcile_without_a_single_base_comparison(monkeypatch):
    from dopplergeist import episodes
    s=DiscoverySettings()
    paths=[track(coordinates(scale=k),str(k)) for k in (1,2,3,4)]
    original=episodes.related
    def graph(a,b,settings):
        if max(np.median(a[:,1]),np.median(b[:,1]))/min(np.median(a[:,1]),np.median(b[:,1]))>3.5:
            return None
        return original(a,b,settings)
    monkeypatch.setattr(episodes,'related',graph)
    for order in [paths,paths[::-1]]:
        assert len(reconcile(order,s,Associations(s)))==1


def test_overlap_alone_does_not_merge_independent_evolution():
    s=DiscoverySettings()
    paths=[track(coordinates(), 'a'),track(coordinates(scale=1.5,rising=True),'b')]
    assert len(reconcile(paths,s,Associations(s)))==2


def test_near_unison_same_chunk_is_not_discarded_as_duplicate():
    s=DiscoverySettings()
    a=coordinates(); b=a.copy(); b[:,1]+=.2
    assert len(deduplicate([track(a),track(b)],s,Associations(s)))==2
    copies=[track(a,'chunk1'),track(a.copy(),'chunk2')]
    for order in [copies,copies[::-1]]:
        merged=deduplicate(order,s,Associations(s))
        assert len(merged)==1 and len(merged[0].origins)==2
        assert np.array_equal(merged[0].points,a)


def test_subthreshold_fragments_stitch_before_duration_gate_and_keep_gap():
    s=DiscoverySettings()
    first=track(coordinates(0,8),'a'); second=track(coordinates(10,18),'b')
    assert motion(first.points,s)[0]['observed_duration_s']<s.min_duration_s
    merged=stitch([second,first],s,Associations(s))
    assert len(merged)==1
    assert not any(8<=t<10 for t in merged[0].points[:,0])
    metric,rejected=motion(merged[0].points,s)
    assert not rejected
    assert metric['observed_duration_s']<metric['span_s']
    competitor=track(coordinates(10.5,18.5),'c')
    assert len(stitch([first,second,competitor],s,Associations(s)))==3
    assert len(stitch([first,track(coordinates(30,38),'c')],s,Associations(s)))==2


def test_time_aware_discontinuity_and_symmetric_directions():
    s=DiscoverySettings()
    for rising in [False,True]:
        p=coordinates(0,40,rising=rising)
        # Irregular observations on the same line retain elapsed-time motion.
        p=np.delete(p,np.arange(5,len(p),6),axis=0)
        metric,rejected=motion(p,s)
        assert not rejected
        assert metric['direction']==('rising' if rising else 'falling')
    p=coordinates(0,40)
    p[:,1]=200+2*np.abs(p[:,0]-20)
    metric,rejected=motion(p,s)
    assert not rejected and metric['direction']=='turning'
    stationary=coordinates(0,40);stationary[:,1]=200
    assert any(r['reason']=='unresolved_frequency_motion' for r in motion(stationary,s)[1])
    switching=stationary.copy();switching[len(switching)//2:,1]=180
    assert any(r['reason']=='insufficient_distributed_motion' for r in motion(switching,s)[1])


def test_association_budget_and_rate_bounds_are_explicit():
    s=replace(DiscoverySettings(),max_associations=1)
    work=Associations(s);work.charge()
    with pytest.raises(DiscoveryError,match='exceeded'):
        work.charge()
    assert required_sample_rate(DiscoverySettings(max_frequency_hz=6000))==16000
    with pytest.raises(ValueError):
        DiscoverySettings(max_frequency_hz=20000)
    with pytest.raises(ValueError,match='two cycles'):
        DiscoverySettings(min_frequency_hz=.1)


@pytest.fixture
def real_recording(tmp_path):
    fixture=json.loads((Path(__file__).parent/'fixtures/real_discovery_normalization.json').read_text())
    excerpt=fixture['excerpts'][0]
    data=np.frombuffer(base64.b64decode(excerpt['pcm_f32le_base64']),dtype='<f4')
    source=tmp_path/'real.wav'
    sf.write(source,data,fixture['sample_rate_hz'],subtype='FLOAT')
    return intake_recording(source,tmp_path/'intake')


def test_real_short_recording_is_a_valid_zero_and_unsupported_coverage_fails(real_recording,tmp_path):
    # A <window excerpt has no complete spectral observation; not a noise claim.
    real_recording.metadata['duration_s']=.5
    with real_recording.samples_path.open('r+b') as stream:
        stream.truncate(round(.5*real_recording.metadata['sample_rate_hz'])*4)
    assert discover_events(real_recording,output_dir=tmp_path/'zero',plot_summary=False)==[]
    report=json.loads((tmp_path/'zero/discovery.json').read_text())
    assert report['status']=='complete' and report['counts']['canonical_proposals']==0
    with pytest.raises(DiscoveryError,match='coverage'):
        discover_events(real_recording,settings=DiscoverySettings(max_frequency_hz=6000),output_dir=tmp_path/'unsupported')
    assert json.loads((tmp_path/'unsupported/discovery.json').read_text())['status']=='failed'


def test_real_spectrum_budget_is_checked_before_allocation(real_recording):
    data=next(real_recording.iter_chunks())[1]
    with pytest.raises(DiscoveryError,match='cells'):
        _spectrum(data,real_recording.metadata['sample_rate_hz'],0,replace(DiscoverySettings(),max_spectral_cells=1))


def test_corrupt_input_is_execution_failure(tmp_path):
    source=tmp_path/'corrupt.mp3';source.write_bytes(b'not an audio stream')
    with pytest.raises(AudioIntakeError) as exc:
        intake_recording(source,tmp_path/'intake')
    assert exc.value.code=='invalid_media'


def test_measured_real_children_adapt_once_per_canonical_episode():
    fixture=json.loads((Path(__file__).parent/'fixtures/real_episode_children.json').read_text())
    from dopplergeist.contracts import validate_event
    events=[validate_event(e) for e in fixture['events']]
    prepared,measurements=prepare_events(events)
    assert len(prepared)==len({e['harmonic_group_id'] for e in events})==1
    assert len(measurements[0][1])==sum(len(e['ridge']) for e in events)
    assert len(prepared[0]['event_ids'])==len(events)
    # Canonical IDs and consumers are invariant to child enumeration.
    other,_=prepare_events(events[::-1])
    assert set(other[0]['event_ids'])==set(prepared[0]['event_ids'])


def test_acoustic_only_brief_evidence_does_not_break_matching_adapter():
    fixture=json.loads((Path(__file__).parent/'fixtures/real_episode_children.json').read_text())
    events=fixture['events']
    for event in events:
        event['quality']['matching_eligible']=0.
    assert prepare_events(events)==([],[])


def test_repeated_reversals_are_not_a_single_supported_turn():
    # Mathematical triangle path; no waveform or empirical signal claim.
    p=coordinates(0,80)
    p[:,1]=200+2*np.abs((p[:,0]%20)-10)
    _,reasons=motion(p,DiscoverySettings())
    assert any(r['reason'] in {'repeated_modulation','wandering_or_modulation'} for r in reasons)


def test_narrow_unanalyzable_band_is_an_explicit_failure(real_recording,tmp_path):
    settings=DiscoverySettings(min_frequency_hz=100,max_frequency_hz=100.5)
    with pytest.raises(DiscoveryError,match='three spectral bins'):
        discover_events(real_recording,settings=settings,output_dir=tmp_path/'narrow')


def test_unexpected_execution_error_cannot_leave_a_complete_negative(real_recording,tmp_path,monkeypatch):
    from dopplergeist import discovery
    def failure(*args):
        raise RuntimeError('controlled execution failure')
    monkeypatch.setattr(discovery,'_paths',failure)
    with pytest.raises(RuntimeError):
        discover_events(real_recording,output_dir=tmp_path/'error')
    report=json.loads((tmp_path/'error/discovery.json').read_text())
    assert report['status']=='failed'
    assert report['failure']['code']=='discovery_execution_error'
