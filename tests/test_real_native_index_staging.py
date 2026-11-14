"""Compare staging on unchanged recorded traces; no generated observations."""
from pathlib import Path

import pytest

from dopplergeist import data_access as access


FIXTURES = [Path(__file__).parent / "fixtures" / f"real-native-index-{i:02d}.json.gz" for i in (1, 2)]
CLASSES = {"B190": "turbine", "C72R": "piston"}
COVERAGE = {"bounds": [-180, -90, 180, 90], "time_range_s": [1778976000, 1779062400],
            "all_aircraft": False, "aircraft_policy": "selected_nonjet_subset",
            "selection": "Two original native traces; incomplete source coverage"}


def batches(paths):
    return [access._archive_nonjet_staging(
        access._decode_archive_frame(path.read_bytes(), 64 * 1024**2), CLASSES) for path in paths]


def sources():
    return [{"path": str(path), "sha256": access.sha256(path), "bytes": path.stat().st_size} for path in FIXTURES]


@pytest.mark.parametrize("order", ["forward", "reverse", "repeated_delivery"])
def test_native_staging_preserves_all_segments_bounds_and_prepared_payloads(tmp_path, monkeypatch, order):
    monkeypatch.setattr(access, "_index_workers", lambda: 1)
    paths = FIXTURES[::-1] if order == "reverse" else FIXTURES
    if order == "repeated_delivery":
        paths = paths + [paths[0]]
    values = []
    for compressed in (False, True):
        index = access.FlightIndex.build(tmp_path / f"{compressed}.sqlite", batches(paths),
            sources=sources(), coverage=COVERAGE, class_map=CLASSES, prepared=True,
            compressed_staging=compressed)
        with index.connect() as db:
            tables = [db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                      for table in ("segments", "spatial", "prepared_tracks")]
        assert tables[0] and tables[2]
        assert index.coverage_for(COVERAGE["bounds"], COVERAGE["time_range_s"])["scope_complete"] is False
        values.append((tables, index.report))
    assert values[0] == values[1]


@pytest.mark.parametrize("compressed", [False, True])
def test_real_trace_sample_budget_failure_publishes_no_index(tmp_path, monkeypatch, compressed):
    monkeypatch.setattr(access, "_index_workers", lambda: 1)
    path = tmp_path / "limited.sqlite"
    with pytest.raises(access.DataUnavailable, match="sample memory limit"):
        access.FlightIndex.build(path, batches(FIXTURES), sources=sources(), coverage=COVERAGE,
            class_map=CLASSES, prepared=True, compressed_staging=compressed, max_flight_samples=1)
    assert not path.exists() and not path.with_suffix(".building").exists()


def test_mixed_aircraft_native_batch_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(access, "_index_workers", lambda: 1)
    first, second = batches(FIXTURES)
    mixed = (first[0] + second[0], first[1] + second[1], {})
    path = tmp_path / "mixed.sqlite"
    with pytest.raises(access.DataUnavailable, match="multiple aircraft"):
        access.FlightIndex.build(path, [mixed], sources=sources(), coverage=COVERAGE,
            class_map=CLASSES, prepared=True, compressed_staging=True)
    assert not path.exists() and not path.with_suffix(".building").exists()
