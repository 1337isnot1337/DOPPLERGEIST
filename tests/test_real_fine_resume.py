"""Optional fine-checkpoint restart checks using recorded audio and aircraft."""
import json
import os
from pathlib import Path
import shutil

import pytest

from dopplergeist.data_access import DataUnavailable, FlightIndex
from dopplergeist.matching import prepare_events
from dopplergeist.terrain import Terrain
from dopplergeist.tiled_search import SearchBudget, search_national


@pytest.mark.parametrize('workers', [1, 2])
def test_real_fine_checkpoints_resume_and_reject_corruption(tmp_path, monkeypatch, workers):
    names = ('DOPPLERGEIST_REAL_TERRAIN_DEM', 'DOPPLERGEIST_REAL_TERRAIN_GEOID',
             'DOPPLERGEIST_REAL_TERRAIN_FLIGHT_INDEX', 'DOPPLERGEIST_REAL_TILE_JOB')
    values = [os.environ.get(name) for name in names]
    if not all(values):
        pytest.skip('set real terrain, index and ESID 762 job paths')
    dem, geoid, index_path, saved_job = values
    job = Path(saved_job)
    config = json.loads((job / 'search/manifest.json').read_text())['configuration']
    raw = json.loads((job / 'discovery/discovery.json').read_text())['events']
    events, measurements = prepare_events(raw, c=343.0, max_distance_m=20000.0)

    def run(output, count):
        terrain = Terrain([dem], geoid_path=geoid)
        try:
            return search_national([FlightIndex(index_path)], terrain, events, measurements,
                time_range_s=config['time_range_s'], output_dir=output, bounds=config['bounds'],
                budget=SearchBudget(**config['budget']), scoring=config['scoring'], filters=config['filters'],
                crs=config['crs'], input_hashes=config['additional_input_hashes'], workers=count)
        finally:
            for raster in terrain.rasters + terrain.geoid.rasters:
                raster.close()

    baseline = run(tmp_path / 'baseline', workers)
    import dopplergeist.tiled_search as tiled
    write = tiled.write_json
    calls = []

    def interrupt_after_three(path, value, **kwargs):
        write(path, value, **kwargs)
        if Path(path).name.startswith('fine-tile-'):
            calls.append(path)
            if len(calls) == 3:
                raise KeyboardInterrupt

    output = tmp_path / 'interrupted'
    with monkeypatch.context() as patch:
        patch.setattr(tiled, 'write_json', interrupt_after_three)
        with pytest.raises(KeyboardInterrupt):
            run(output, workers)
    assert len(list(output.glob('fine-tile-*.json'))) == 3
    resumed = run(output, workers)
    assert resumed['refinement_stages_resumed'] >= 3
    assert resumed['ranked'] == baseline['ranked']
    assert resumed['model_support'] == baseline['model_support']
    assert resumed['finite_search_evidence'] == baseline['finite_search_evidence']
    assert resumed['refinement_failure'] is None
    with pytest.raises(DataUnavailable, match='worker count|configuration/input/implementation mismatch'):
        run(output, 1 if workers == 2 else 2)

    if workers == 2:
        before_fine = tmp_path / 'before-fine-checkpoint'

        def interrupt_before_first_fine(path, value, **kwargs):
            if Path(path).name == 'fine-checkpoint-config.json':
                raise KeyboardInterrupt
            write(path, value, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(tiled, 'write_json', interrupt_before_first_fine)
            with pytest.raises(KeyboardInterrupt):
                run(before_fine, 2)
        assert not list(before_fine.glob('fine-tile-*.json'))
        more_workers = run(before_fine, 3)
        assert more_workers['tiles_resumed'] > 0
        assert more_workers['refinement_failure'] is None
        assert more_workers['ranked'] == baseline['ranked']
        fresh_more_workers = run(tmp_path / 'fresh-more-workers', 3)
        assert more_workers['ranked'] == fresh_more_workers['ranked']
        assert more_workers['model_support'] == fresh_more_workers['model_support']
        assert more_workers['finite_search_evidence'] == fresh_more_workers['finite_search_evidence']

    corrupt = tmp_path / 'corrupt'
    shutil.copytree(output, corrupt)
    checkpoint = next(corrupt.glob('fine-tile-*.json'))
    data = json.loads(checkpoint.read_text())
    floor = data['parameters']['score_floor']
    data['parameters']['score_floor'] = 1.0 if floor is None else floor + 1.0
    checkpoint.write_text(json.dumps(data))
    damaged = run(corrupt, workers)
    assert damaged['status'] == 'partial'
    assert 'Corrupt fine-tile checkpoint' in damaged['refinement_failure']
