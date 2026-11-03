"""Worker-count configuration using the saved original upload and real index."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dopplergeist.automatic import _search, analyze
import dopplergeist.tiled_search as tiled


def test_real_upload_worker_setting_reaches_search(tmp_path, monkeypatch):
    source, index, reference, terrain = (os.environ.get(name) for name in (
        'DOPPLERGEIST_REAL_JOB_ROOT', 'DOPPLERGEIST_REAL_DEVELOPMENT_INDEX',
        'DOPPLERGEIST_REAL_REFERENCE_ROOT', 'DOPPLERGEIST_REAL_ENGINEERING_TERRAIN'))
    if not all((source, index, reference, terrain)):
        pytest.skip('set the real job, development index, reference and terrain paths')
    job, reference, terrain = Path(source), Path(reference), Path(terrain)
    request = json.loads((job / 'request.json').read_text())
    metadata = json.loads((job / 'intake/recording.json').read_text())
    events = json.loads((job / 'discovery/discovery.json').read_text())['events']
    config = {'search_workers': 12, 'flight_indexes': [index], 'terrain': {
        'rasters': [str(reference / 'data/terrain/copernicus90/Copernicus_DSM_COG_30_N40_00_W074_00_DEM.tif')],
        'geoid_raster': str(terrain / 'us_nga_egm08_25.tif')}}
    captured = []
    class StopBeforeScoring(Exception):
        pass
    def stop(*args, **kwargs):
        captured.append(kwargs['workers'])
        raise StopBeforeScoring
    monkeypatch.setattr(tiled, 'search_national', stop)
    with pytest.raises(StopBeforeScoring):
        _search(request, SimpleNamespace(metadata=metadata), events, tmp_path, config, lambda *_: None)
    assert captured == [12]

    for i, invalid in enumerate((0, -1, True, 1.5, '12')):
        result = analyze(request, tmp_path / str(i), {'search_workers': invalid})
        assert result['status'] == 'failed' and result['reason_code'] == 'invalid_configuration'
