"""Selection checks using confirmed non-jet recorded observations."""
import json
from pathlib import Path

import pandas as pd

from dopplergeist.data_access import FlightIndex, _archive_nonjet_staging
from dopplergeist.tiled_search import SearchBudget, _tracks


def test_confirmed_nonjet_tracks_are_selected(tmp_path):
    source = Path(__file__).resolve().parents[1] / "research/trajectory-motion/frozen/canonical-observations.json"
    rows = [row for row in json.loads(source.read_text()) if row.get("typecode") in ("C172", "H500")]
    frame = pd.DataFrame(rows)
    assert len(frame) > 0
    bounds = [-180.0, -90.0, 180.0, 90.0]
    window = [float(frame.time_s.min()), float(frame.time_s.max())]
    index = FlightIndex.build(tmp_path / "nonjet.sqlite", [frame], sources=[],
                              coverage={"bounds": bounds, "time_range_s": window, "all_aircraft": False},
                              class_map={"C172": "piston", "H500": "turbine"})
    selected = _tracks([index], bounds, window, SearchBudget())
    assert selected
    assert all(track.aircraft_class in ("piston", "turbine") for track in selected)
    assert {track.typecode for track in selected}.issubset({"C172", "H500"})


def test_archive_staging_retains_confirmed_nonjet_observations():
    source = Path(__file__).resolve().parents[1] / "research/trajectory-motion/frozen/canonical-observations.json"
    rows = [row for row in json.loads(source.read_text()) if row.get("typecode") in ("C172", "H500")]
    frame = pd.DataFrame(rows)
    staged = []
    for _, group in frame.groupby("flight_id"):
        batch, _, _ = _archive_nonjet_staging(group, {"C172": "piston", "H500": "turbine"})
        staged.extend(json.loads(payload) for _, _, payload in batch)
    assert len(staged) > 0
    assert all(row["aircraft_class"] in ("piston", "turbine") for row in staged)
    assert {row["typecode"] for row in staged}.issubset({"C172", "H500"})


def test_missing_classification_does_not_claim_complete_search():
    from dopplergeist.automatic import _coverage
    search = {"tiles_total": 1, "tiles_completed": 1, "tile_failures": [],
              "refinement_failure": None, "all_event_groups_considered": True,
              "data_scope_complete": True, "aircraft_scope": "confirmed_nonjet",
              "aircraft_classification_incomplete": True}
    coverage = _coverage({"search": {"coverage": "regional"}}, search, {})
    assert coverage["search_complete"] is False
    assert any("metadata may be missing" in item for item in coverage["limitations"])
