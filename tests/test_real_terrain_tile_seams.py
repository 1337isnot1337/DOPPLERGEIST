"""Tile ownership checked against actual public Copernicus raster headers."""
import json
from pathlib import Path

import numpy as np
import pytest

from dopplergeist.terrain import _glo90_tile_degrees


OBSERVED = json.loads((Path(__file__).parent / "data" / "real-glo90-tile-headers.json").read_text())
RASTERS = {(r["north"], r["east"]): r for r in OBSERVED["rasters"]}


@pytest.mark.parametrize("raster", OBSERVED["rasters"], ids=lambda r: r["tile"])
def test_actual_raster_western_strip_belongs_to_its_tile(raster):
    west, south, east, north = raster["bounds_wsen"]
    # This is a real strip inside the observed first column. The old fixed
    # half-pixel selects the previous longitude tile at wider latitude bands.
    lat = (south + north) / 2
    lon = west + raster["pixel_width_degrees"] / 10
    assert west <= lon < east and south < lat <= north
    assert _glo90_tile_degrees([lat], [lon]).tolist() == [[raster["north"], raster["east"]]]


def test_actual_brandenburg_seam_and_berlin_centre():
    points = [(52.52, 13.9995), (52.52, 13.405)]
    selected = _glo90_tile_degrees(*np.asarray(points).T)
    assert selected.tolist() == [[52, 14], [52, 13]]
    for (lat, lon), pair in zip(points, selected):
        raster = RASTERS[tuple(pair)]
        west, south, east, north = raster["bounds_wsen"]
        assert west <= lon < east and south < lat <= north


def test_actual_n49_n50_shared_latitude_edge_and_different_widths():
    edge = RASTERS[49, 13]["bounds_wsen"][3]
    assert edge == RASTERS[50, 14]["bounds_wsen"][1]
    # The shifted shared edge belongs to N49. Above it, the same longitude
    # belongs to N50E014 because N50's longitude columns are wider.
    lat = np.array([edge - 1e-7, edge, edge + 1e-7])
    lon = np.full(3, 13.9995)
    assert _glo90_tile_degrees(lat, lon).tolist() == [[49, 13], [49, 13], [50, 14]]


def test_actual_s50_s51_have_different_longitude_widths():
    lower_latitude = RASTERS[-50, -74]
    higher_latitude = RASTERS[-51, -74]
    assert lower_latitude["width"] == 1200
    assert higher_latitude["width"] == 800
    # Absolute tile origin would incorrectly classify S50 as the wider band,
    # moving this observed eastern strip into W073 instead of W074.
    lon = lower_latitude["bounds_wsen"][2] - lower_latitude["pixel_width_degrees"] / 10
    assert _glo90_tile_degrees([-49.5], [lon]).tolist() == [[-50, -74]]
