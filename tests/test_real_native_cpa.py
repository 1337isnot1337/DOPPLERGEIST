"""Native CPA parity on the repository's frozen real ADS-B observations."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import numpy as np
import pytest

from dopplergeist import native_cpa, search
from dopplergeist.geometry import AcousticSupportError, ecef


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "benchmark_real_cpa_rows", ROOT / "scripts/benchmark_real_cpa_rows.py")
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


@pytest.fixture(scope="module")
def tracks():
    return BENCHMARK.recorded_tracks()


@pytest.fixture
def backend():
    if native_cpa._native is None:
        pytest.skip("optional CPA extension is not built")
    return native_cpa._native


def assert_exact(before, after):
    BENCHMARK.compare(before, after)
    for column in ("emission_time", "receive_time", "distance_m", "speed_mps"):
        # Include signed-zero bits, not just pandas' numerical equality.
        assert before[0][column].to_numpy().tobytes() == after[0][column].to_numpy().tobytes()


@pytest.mark.parametrize("count", [1, 32, 128, 1024])
@pytest.mark.parametrize("radius,c,step,chunk", [
    (1000., 343., 2., 512), (20000., 343., 2., 512),
    (20000., 338., 1., 7), (20000., 348., 8., 1),
    (20000., 343., np.float32(2.), 512),
])
def test_recorded_tables_and_unsupported_accounting(tracks, backend, count, radius, c, step, chunk):
    points = BENCHMARK.recorded_points(tracks, count)
    with patch.object(native_cpa, "_native", None):
        expected = BENCHMARK.cpa_stage(search, tracks, points, radius, c, step, chunk, True)
    actual = BENCHMARK.cpa_stage(search, tracks, points, radius, c, step, chunk, True)
    assert_exact(expected, actual)


def test_raw_endpoint_and_interior_order_with_repeated_wide_ids(tracks, backend):
    points = BENCHMARK.recorded_points(tracks, 1024).iloc[::-1].copy()
    points["point_id"] = np.arange(len(points), dtype=np.int64)//2 + 2**53
    observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
    calls = backend.successful_calls()
    retained = 0
    with patch.object(search, "minimize_scalar", wraps=search.minimize_scalar) as endpoint:
        for track in tracks:
            try:
                prepared = search._PreparedCPATrack(track, 343., 2.)
            except AcousticSupportError:
                continue
            with patch.object(native_cpa, "_native", None):
                expected = prepared.raw_rows(observers, points.point_id.to_numpy(), 20000.)
            actual = prepared.raw_rows(observers, points.point_id.to_numpy(), 20000.)
            assert [(row[:2], np.asarray(row[2:]).tobytes()) for row in actual] == [
                (row[:2], np.asarray(row[2:]).tobytes()) for row in expected]
            assert search._ordered_cpa_rows(actual, 2.) == search._ordered_cpa_rows(expected, 2.)
            retained += len(actual)
    assert retained > 0
    assert endpoint.call_count > 0
    assert backend.successful_calls() > calls


@pytest.mark.parametrize("policy", ["raise", "ignore", "warn"])
def test_nondefault_error_policy_uses_reference(tracks, backend, policy):
    points = BENCHMARK.recorded_points(tracks, 32)
    calls = backend.successful_calls()
    with np.errstate(all=policy):
        with patch.object(native_cpa, "_native", None):
            expected = BENCHMARK.cpa_stage(search, tracks, points, row_mode=True)
        actual = BENCHMARK.cpa_stage(search, tracks, points, row_mode=True)
    assert_exact(expected, actual)
    assert backend.successful_calls() == calls


@pytest.fixture
def graph(tracks):
    supported = []
    for track in tracks:
        try:
            track.validate_motion_support()
            supported.append(track)
        except AcousticSupportError:
            pass
    track = max(supported, key=lambda item: item.time[-1]-item.time[0])
    prepared = search._PreparedCPATrack(track, 343., 2.)
    points = BENCHMARK.recorded_points([track], 32)
    observers = np.ascontiguousarray(ecef(points.lat.to_numpy(), points.lon.to_numpy(),
                                          points.elev_m.to_numpy()))
    neighbours = search.cKDTree(prepared.position).query_ball_point(
        observers, 20000.+2*prepared.max_step, return_sorted=True)
    counts = np.fromiter(map(len, neighbours), dtype=np.intp)
    sample = np.concatenate(neighbours).astype(np.intp)
    return prepared.position, observers, counts, sample


@pytest.mark.parametrize("index", range(4))
def test_strided_same_observations_use_reference(graph, backend, index):
    inputs = list(graph)
    inputs[index] = np.repeat(inputs[index], 2, axis=0)[::2]
    assert not inputs[index].flags.c_contiguous
    calls = backend.successful_calls()
    assert native_cpa.try_cpa_edges(*inputs) is None
    assert backend.successful_calls() == calls


def test_readonly_buffers_and_empty_neighbour_groups(graph, backend):
    expected = native_cpa.try_cpa_edges(*graph)
    assert expected is not None
    for array in graph:
        array.flags.writeable = False
    actual = native_cpa.try_cpa_edges(*graph)
    for left, right in zip((*actual[0], *actual[1:]), (*expected[0], *expected[1:])):
        assert left.dtype == right.dtype
        assert left.shape == right.shape
        assert left.tobytes() == right.tobytes()
    # An empty receiver chunk must return no candidate proposals.
    far_observers = graph[1][:0]
    empty = native_cpa.try_cpa_edges(graph[0], far_observers, graph[2][:0], graph[3][:0])
    assert empty is not None
    assert all(array.size == 0 for array in (*empty[0], *empty[1:]))


def test_native_rejects_invalid_graph_metadata_and_output_aliases(graph, backend):
    position, observers, counts, sample = graph
    capacity = sample.size//2
    endpoints = np.empty((2, len(observers)), dtype=np.intp)
    indices = np.empty((2, capacity), dtype=np.intp)
    values = np.empty((2, capacity), dtype=np.float64)
    changed = counts.copy()
    changed[0] = -1
    assert backend.select(position, observers, changed, sample, endpoints, indices, values) is None
    changed = sample.copy()
    changed[0] = len(position)
    assert backend.select(position, observers, counts, changed, endpoints, indices, values) is None
    assert backend.select(position, observers, counts, sample[:-1], endpoints, indices, values) is None
    assert backend.select(position, observers, counts, sample, endpoints, indices[:, :-1], values) is None
    # Writable output must never overwrite neighbour indices while C reads them.
    storage = np.empty(max(sample.size, endpoints.size), dtype=np.intp)
    storage[:sample.size] = sample
    alias = storage[:endpoints.size].reshape(endpoints.shape)
    before = storage.tobytes()
    assert backend.select(position, observers, counts, storage[:sample.size], alias, indices, values) is None
    assert storage.tobytes() == before
    before = values.tobytes()
    assert backend.select(position, observers, counts, sample, endpoints,
                          values.view(np.intp), values) is None
    assert values.tobytes() == before


def test_backend_selection_and_source_only_import():
    code = "from dopplergeist.native_cpa import CPA_BACKEND; print(CPA_BACKEND)"
    environment = dict(os.environ, DOPPLERGEIST_CPA_BACKEND="python")
    result = subprocess.run([sys.executable, "-c", code], env=environment,
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "python-cpa-v1"
    environment["DOPPLERGEIST_CPA_BACKEND"] = "auto"
    result = subprocess.run([sys.executable, "-c", code], env=environment,
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() in {"python-cpa-v1", "native-c-cpa-v1"}
    missing = "import sys; sys.modules['dopplergeist._native_cpa'] = None; " + code
    result = subprocess.run([sys.executable, "-c", missing], env=environment,
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "python-cpa-v1"
    environment["DOPPLERGEIST_CPA_BACKEND"] = "unknown"
    result = subprocess.run([sys.executable, "-c", code], env=environment,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "DOPPLERGEIST_CPA_BACKEND must be" in result.stderr
