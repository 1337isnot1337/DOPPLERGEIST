import concurrent.futures
from concurrent.futures import Future

from dopplergeist import parallel_tiles
from dopplergeist.parallel_tiles import WorkerAffinePool


class ImmediatePool:
    def __init__(self):
        self.stages = []

    def submit(self, function, stage, cells, score_floor):
        self.stages.append(stage)
        future = Future()
        try:
            future.set_result(function(stage, cells, score_floor))
        except BaseException as error:
            future.set_exception(error)
        return future


def _scored_tile(stage, cells, score_floor):
    return {"stage": stage}, None, tuple(cells)


def test_affinity_routes_to_resident_dem_and_preserves_result_order(monkeypatch):
    lanes = [ImmediatePool(), ImmediatePool()]
    pool = WorkerAffinePool(lanes, lambda cells: cells, lambda result: result[2], chunk_size=1)
    monkeypatch.setattr(parallel_tiles, "score_tile_with_cache_state", _scored_tile)
    jobs = [(f"coarse:{name}", (dem,), None, None)
            for name, dem in (("first", "A"), ("second", "B"), ("third", "A"))]

    results = list(parallel_tiles.ordered_tile_results(
        pool, jobs, 2, lambda stage, cells, future: future.result()[0]))

    assert [(stage, result, cached) for stage, _, result, cached in results] == [
        (stage, {"stage": stage}, False) for stage, _, _, _ in jobs]
    assert lanes[0].stages == ["coarse:first", "coarse:third"]
    assert lanes[1].stages == ["coarse:second"]


def test_tiles_in_a_small_spatial_chunk_stay_on_one_worker(monkeypatch):
    lanes = [ImmediatePool(), ImmediatePool()]
    pool = WorkerAffinePool(lanes, lambda cells: cells, lambda result: result[2], chunk_size=2)
    monkeypatch.setattr(parallel_tiles, "score_tile_with_cache_state", _scored_tile)
    jobs = [(f"coarse:{name}", (dem,), None, None)
            for name, dem in (("first", "A"), ("second", "A"), ("third", "B"), ("fourth", "B"))]

    results = list(parallel_tiles.ordered_tile_results(
        pool, jobs, 2, lambda stage, cells, future: future.result()[0]))

    assert [result[0] for result in results] == [stage for stage, _, _, _ in jobs]
    assert lanes[0].stages == ["coarse:first", "coarse:second"]
    assert lanes[1].stages == ["coarse:third", "coarse:fourth"]


def test_ordered_tile_results_reads_only_a_bounded_window_before_first_yield(monkeypatch):
    lanes = [ImmediatePool(), ImmediatePool()]
    pool = WorkerAffinePool(lanes, lambda cells: cells, lambda result: result[2], chunk_size=2)
    monkeypatch.setattr(parallel_tiles, "score_tile_with_cache_state", _scored_tile)
    consumed = []

    def jobs():
        for i in range(20):
            consumed.append(i)
            yield f"coarse:{i}", (str(i),), None, None

    results = parallel_tiles.ordered_tile_results(pool, jobs(), 2,
                                                  lambda stage, cells, future: future.result()[0])
    first = next(results)

    assert first[0] == "coarse:0"
    assert len(consumed) <= 4


def test_completed_later_tiles_do_not_expand_the_window(monkeypatch):
    lanes = [ImmediatePool(), ImmediatePool()]
    pool = WorkerAffinePool(lanes, lambda cells: cells, lambda result: result[2], chunk_size=2)
    monkeypatch.setattr(parallel_tiles, "score_tile_with_cache_state", _scored_tile)
    consumed = []
    waits = 0
    first_future = None

    def submit(function, stage, cells, score_floor):
        nonlocal first_future
        future = Future()
        if first_future is None:
            first_future = future
        else:
            future.set_result(function(stage, cells, score_floor))
        return future

    monkeypatch.setattr(pool.pools[0], "submit", submit)
    monkeypatch.setattr(pool.pools[1], "submit", submit)

    def wait(futures, return_when):
        nonlocal waits
        waits += 1
        if waits == 1:
            completed = {future for future in futures if future is not first_future}
            return completed, set(futures) - completed
        first_future.set_result(_scored_tile("coarse:0", ("0",), None))
        return {first_future}, set(futures) - {first_future}

    monkeypatch.setattr(concurrent.futures, "wait", wait)

    def jobs():
        for i in range(20):
            consumed.append(i)
            yield f"coarse:{i}", (str(i),), None, None

    results = parallel_tiles.ordered_tile_results(pool, jobs(), 2,
                                                  lambda stage, cells, future: future.result()[0])
    assert next(results)[0] == "coarse:0"
    assert consumed == [0, 1, 2, 3]
