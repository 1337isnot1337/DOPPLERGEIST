"""Resume hash reuse and mutation checks using a real cached terrain raster."""
from collections import OrderedDict
import json
import os
from pathlib import Path
import shutil

import pytest

from dopplergeist import tiled_search
from dopplergeist.data_access import DataUnavailable


@pytest.fixture
def real_geoid_copy(tmp_path):
    cache = os.environ.get('DOPPLERGEIST_REAL_CACHE_ROOT')
    if not cache:
        pytest.skip('set DOPPLERGEIST_REAL_CACHE_ROOT to the real terrain cache')
    source = Path(cache)/'terrain/us_nga_egm08_25.tif'
    target = tmp_path/source.name
    shutil.copyfile(source, target)
    return target


def test_real_terrain_hash_is_reused_and_changed_content_is_detected(real_geoid_copy, monkeypatch):
    path = real_geoid_copy
    original = tiled_search.sha256
    calls = []
    def counted(file):
        calls.append(file)
        return original(file)
    monkeypatch.setattr(tiled_search, 'sha256', counted)
    cache = OrderedDict()
    first = tiled_search._verified_terrain_hash(path, cache)
    assert tiled_search._verified_terrain_hash(path, cache) == first
    assert len(calls) == 1
    stat = path.stat()
    with path.open('r+b') as file:
        file.seek(-1, os.SEEK_END)
        original_byte = file.read(1)
        file.seek(-1, os.SEEK_END)
        file.write(bytes([original_byte[0] ^ 1]))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size and path.stat().st_mtime_ns == stat.st_mtime_ns
    assert tiled_search._verified_terrain_hash(path, cache) != first
    assert len(calls) == 2


def test_real_terrain_change_during_hash_fails_closed(real_geoid_copy, monkeypatch):
    path = real_geoid_copy
    original = tiled_search.sha256
    def change_after_hash(file):
        digest = original(file)
        with Path(file).open('ab') as target:
            target.write(b'\0')
        return digest
    monkeypatch.setattr(tiled_search, 'sha256', change_after_hash)
    with pytest.raises(DataUnavailable, match='changed while hashing'):
        tiled_search._verified_terrain_hash(path, OrderedDict())


def test_real_saved_tile_terrain_receipts_validate_and_reuse(monkeypatch):
    job = os.environ.get('DOPPLERGEIST_REAL_JOB_ROOT')
    if not job:
        pytest.skip('set DOPPLERGEIST_REAL_JOB_ROOT to the real saved job')
    receipt = json.loads((Path(job)/'search/tile--15_7.json').read_text())['payload']
    files = receipt['terrain_files']
    assert files
    original = tiled_search.sha256
    calls = []
    def counted(file):
        calls.append(file)
        return original(file)
    monkeypatch.setattr(tiled_search, 'sha256', counted)
    cache = OrderedDict()
    for _ in range(2):
        for source in files:
            assert tiled_search._verified_terrain_hash(source['path'], cache) == source['sha256']
    assert len(calls) == len({source['path'] for source in files})
