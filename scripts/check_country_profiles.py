#!/usr/bin/env python3
"""Check country contracts and real BKG receiver geometry without audio or tracks.

Run against an installed package, or set PYTHONPATH=src in a checkout:

    python scripts/check_country_profiles.py --cache-root /path/to/cache

The default is offline. --online permits the production loader to acquire its
pinned public BKG feature when absent. No historical-flight or terrain download,
localization run, generated recording, or generated aircraft track is involved.
"""
from copy import deepcopy
import argparse
import json
import math
from pathlib import Path
import pickle
import sys


class CheckFailure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailure(message)


def check_contracts():
    from dopplergeist.contracts import validate_request
    from dopplergeist.geography import profile_for_search, public_profiles

    # This is only request validation. The existing script path is not decoded
    # or represented as a real recording.
    request_base = {"schema_version": 1, "audio_path": str(Path(__file__).resolve())}
    conus_subset = [-90.0, 40.0, -87.0, 43.0]
    buesingen_subset = [8.66, 47.68, 8.72, 47.72]
    cases = (
        ("omitted search", None, {"coverage": "conus"}, "US"),
        ("legacy CONUS", {"coverage": "conus"}, {"coverage": "conus"}, "US"),
        ("legacy CONUS subset", {"coverage": "conus", "bounds_wsen": conus_subset},
         {"coverage": "conus", "bounds_wsen": conus_subset}, "US"),
        ("US country", {"country": "us"}, {"country": "US", "coverage": "conus"}, "US"),
        ("DE country", {"country": "de"}, {"country": "DE", "coverage": "germany"}, "DE"),
        ("Germany coverage", {"coverage": "germany"}, {"coverage": "germany"}, "DE"),
        ("explicit Germany", {"country": "DE", "coverage": "germany"},
         {"country": "DE", "coverage": "germany"}, "DE"),
        ("Germany subset", {"country": "DE", "bounds_wsen": buesingen_subset},
         {"country": "DE", "coverage": "germany", "bounds_wsen": buesingen_subset}, "DE"),
    )
    validated = {}
    for name, search, expected, country in cases:
        request = deepcopy(request_base)
        if search is not None:
            request["search"] = deepcopy(search)
        original = deepcopy(request)
        normalized = validate_request(request)
        require(request == original, f"{name}: validation changed the input request")
        require(normalized["search"] == expected, f"{name}: unexpected normalized search")
        require(profile_for_search(normalized["search"]).country == country,
                f"{name}: wrong resolved country")
        serialized = json.loads(json.dumps(normalized, allow_nan=False))
        require(validate_request(serialized) == normalized,
                f"{name}: normalization is not stable through a JSON round trip")
        validated[name] = normalized

    rejected = (
        {"country": "DE", "coverage": "conus"},
        {"country": "US", "coverage": "germany"},
        {"country": "FR"},
        {"coverage": "custom"},
        {"country": None},
        {"coverage": None},
        {},
        {"country": "DE", "bounds_wsen": conus_subset},
        {"country": "US", "bounds_wsen": buesingen_subset},
        {"country": "DE", "bounds_wsen": [8.72, 47.68, 8.66, 47.72]},
        {"country": "DE", "bounds_wsen": [8.66, 47.68, math.nan, 47.72]},
        {"country": "DE", "unsupported_field": True},
    )
    for search in rejected:
        try:
            validate_request(dict(request_base, search=search))
        except ValueError:
            pass
        else:
            raise CheckFailure(f"Invalid search was accepted: {search!r}")

    catalog = public_profiles()
    require(len(catalog) == 2 and {p["country"] for p in catalog} == {"US", "DE"},
            "Capabilities must describe exactly the supported US and DE profiles")
    for item in catalog:
        profile = profile_for_search({"country": item["country"]})
        require(item["coverage"] == profile.coverage and item["crs"] == profile.crs
                and item["bounds_wsen"] == list(profile.bounds_wsen),
                f"Capabilities disagree with the {profile.country} runtime profile")
    require(profile_for_search().crs == "EPSG:5070", "Legacy CONUS CRS changed")
    require(profile_for_search({"country": "DE"}).crs == "EPSG:32632",
            "Germany must use its declared UTM 32N search CRS")
    print(f"PASS requests: {len(cases)} normalization/JSON round-trip cases; "
          f"{len(rejected)} invalid declarations rejected; profile catalog agrees")
    return validated


# Fixed real locations, not simulated receivers or localization truth.
# The small-component controls use coordinates published by their local bodies:
# Helgoland: https://www.helgoland.de/content/uploads/2024/02/Faltplan-HELGOLAND-GB_web.pdf
# Sylt: https://www.sylt.de/eventlocation/tui-blue-sylt
# Buesingen: routing link at https://www.buesingen.de/de/Rathaus/Gemeindeverwaltung
# Mainland city coordinates are rounded landmarks; they are far from the border.
LOCATIONS = (
    ("Berlin centre", 13.4050, 52.5200, True),
    ("Munich Marienplatz", 11 + 34 / 60 + 31 / 3600, 48 + 8 / 60 + 14 / 3600, True),
    ("Helgoland", 7 + 53 / 60 + 1 / 3600, 54 + 10 / 60 + 57 / 3600, True),
    ("Sylt, Rantum", 8.2949, 54.85991, True),
    ("Buesingen town hall", 8.687434, 47.696354, True),
    ("Zurich centre", 8.5417, 47.3769, False),
    ("Prague centre", 14.4378, 50.0755, False),
    ("Schaffhausen centre", 8.6349, 47.6965, False),
)


def check_mask(cache_root, online, validated):
    import numpy as np
    from dopplergeist.geography import (
        BKG_BOUNDARY_SHA256, BKG_BOUNDARY_URL, profile_for_search, receiver_mask_for_search,
    )

    require(receiver_mask_for_search(validated["legacy CONUS"]["search"],
                                    cache_root=cache_root, offline=True) is None,
            "The legacy CONUS profile unexpectedly acquired a country polygon")
    search = validated["DE country"]["search"]
    mask = receiver_mask_for_search(search, cache_root=cache_root, offline=not online)
    require(mask is not None, "Germany must not fall back to a rectangular mask")
    identity = mask.identity
    require(identity["boundary_sha256"] == BKG_BOUNDARY_SHA256
            and identity["source_url"] == BKG_BOUNDARY_URL,
            "Loaded boundary does not identify the pinned BKG source")
    require(identity["source_crs"] == "EPSG:25832"
            and identity["search_crs"] == profile_for_search(search).crs,
            "Boundary/source CRS identity disagrees with the selected search profile")

    lon = np.array([item[1] for item in LOCATIONS])
    lat = np.array([item[2] for item in LOCATIONS])
    expected = np.array([item[3] for item in LOCATIONS], dtype=bool)
    west, south, east, north = profile_for_search(search).bounds_wsen
    require(bool(np.all((lon >= west) & (lon <= east) & (lat >= south) & (lat <= north))),
            "Named controls must all be inside the Germany rectangular envelope")
    actual = np.asarray(mask.contains(lon, lat), dtype=bool)
    require(actual.shape == expected.shape, "Vector mask changed the coordinate shape")
    mismatches = [item[0] for item, keep, want in zip(LOCATIONS, actual, expected) if keep != want]
    require(not mismatches, f"Incorrect land membership: {', '.join(mismatches)}")
    scalar = np.array([bool(mask.contains(float(x), float(y))) for x, y in zip(lon, lat)])
    require(np.array_equal(actual, scalar), "Scalar and vector country masks disagree")

    # Workers receive the real polygon through serialization. Also reload the
    # actual cache offline after acquisition, so a successful online fetch alone
    # cannot hide an unusable persisted feature.
    transferred = pickle.loads(pickle.dumps(mask, protocol=pickle.HIGHEST_PROTOCOL))
    cached = receiver_mask_for_search(search, cache_root=cache_root, offline=True)
    for name, copy in (("pickled worker mask", transferred), ("offline cache", cached)):
        require(copy.identity == identity, f"{name}: source identity changed")
        require(np.array_equal(copy.contains(lon, lat), expected),
                f"{name}: real-location membership changed")
    require(not mask.boundary_limited(13.4050, 52.5200, 1000.0),
            "Central Berlin was incorrectly flagged within 1 km of the country boundary")
    require(mask.boundary_limited(8.687434, 47.696354, 10000.0),
            "A 10 km neighbourhood of Buesingen must be boundary-limited")
    require(mask.boundary_limited(8.5417, 47.3769, 0.0),
            "An outside-country receiver must be boundary-limited")
    print(f"PASS BKG mask: {int(expected.sum())} German locations retained "
          f"(including two islands and Buesingen); {int((~expected).sum())} foreign locations excluded")
    print("PASS scalar/vector, worker pickle, offline reload and boundary-proximity controls")
    return mask


def check_border_grid(mask, validated):
    import numpy as np
    from pyproj import Transformer
    from dopplergeist.geography import profile_for_search
    from dopplergeist.tiled_search import _tile_coordinates

    profile = profile_for_search(validated["DE country"]["search"])
    forward = Transformer.from_crs("EPSG:4326", profile.crs, always_xy=True)
    # The actual Buesingen exclave and surrounding Swiss territory exercise both
    # sides of a land border, unlike an inland rectangle-only grid check.
    centre_x, centre_y = forward.transform(8.687434, 47.696354)
    subset = validated["Germany subset"]["search"]["bounds_wsen"]
    summaries = []
    for spacing in (1000.0, 250.0):
        cells = (math.floor((centre_x - 6000) / spacing), math.floor((centre_y - 6000) / spacing),
                 math.ceil((centre_x + 6000) / spacing), math.ceil((centre_y + 6000) / spacing))
        for label, bounds in (("national envelope", profile.bounds_wsen), ("requested subset", subset)):
            rectangle = _tile_coordinates(cells, spacing, bounds, profile.crs)
            clipped = _tile_coordinates(cells, spacing, bounds, profile.crs, receiver_mask=mask)
            require(0 < len(clipped) < len(rectangle),
                    f"Buesingen {spacing:g} m/{label}: clipping did not preserve both border sides")
            expected = np.asarray(mask.contains(rectangle.lon.to_numpy(), rectangle.lat.to_numpy()), dtype=bool)
            columns = ["x", "y", "lon", "lat"]
            require(np.array_equal(clipped[columns].to_numpy(), rectangle.loc[expected, columns].to_numpy()),
                    f"Buesingen {spacing:g} m/{label}: the grid lost or added country cells")
            projected_x, projected_y = forward.transform(clipped.lon.to_numpy(), clipped.lat.to_numpy())
            require(np.allclose(projected_x, clipped.x.to_numpy(), rtol=0, atol=1e-5)
                    and np.allclose(projected_y, clipped.y.to_numpy(), rtol=0, atol=1e-5),
                    f"Buesingen {spacing:g} m/{label}: grid x/y disagree with the country CRS")
            summaries.append(f"{spacing:g} m/{label}: {len(rectangle)} -> {len(clipped)} cells")
    print("PASS real border-grid clipping and UTM 32N coordinate agreement: " + "; ".join(summaries))


def check_empty_areas(mask, validated):
    from dopplergeist.geography import EmptySearchArea, profile_for_search
    from dopplergeist.tiled_search import _grid_extent, _tile_coordinates

    profile = profile_for_search(validated["DE country"]["search"])
    foreign = (
        ("Zurich", [8.53, 47.37, 8.55, 47.39]),
        ("Prague", [14.43, 50.07, 14.45, 50.08]),
        ("Schaffhausen", [8.63, 47.69, 8.64, 47.70]),
    )
    for name, bounds in foreign:
        try:
            mask.preflight_grid(bounds, 2000.0, profile.crs)
        except EmptySearchArea as error:
            require(error.reason_code == "empty_search_area",
                    f"{name}: foreign rectangle did not identify an empty country area")
        else:
            raise CheckFailure(f"{name}: foreign rectangle passed the receiver preflight")

    # This real Berlin location is on German land, but the sub-metre rectangle
    # contains no point of the actual 2 km search grid. Check the grid directly
    # before requiring the distinct coarse-resolution explanation.
    small_berlin = [13.404999, 52.519999, 13.405001, 52.520001]
    require(bool(mask.contains(13.4050, 52.5200)), "Berlin land control changed")
    xmin, ymin, xmax, ymax = _grid_extent(small_berlin, 2000.0, profile.crs)
    require(len(_tile_coordinates((xmin, ymin, xmax + 1, ymax + 1), 2000.0,
                                  small_berlin, profile.crs, mask)) == 0,
            "The Berlin small-area control unexpectedly contains a coarse grid point")
    try:
        mask.preflight_grid(small_berlin, 2000.0, profile.crs)
    except EmptySearchArea as error:
        require(error.reason_code == "empty_search_grid",
                "A land selection without coarse receivers must identify the grid limitation")
    else:
        raise CheckFailure("A land selection without coarse receivers passed preflight")

    available = (
        ("Berlin", [13.3, 52.45, 13.5, 52.6], 2000.0),
        ("Helgoland", [7.87, 54.17, 7.90, 54.19], 250.0),
        ("Sylt", [8.28, 54.85, 8.31, 54.87], 250.0),
        ("Buesingen", validated["Germany subset"]["search"]["bounds_wsen"], 1000.0),
    )
    for name, bounds, spacing in available:
        require(mask.preflight_grid(bounds, spacing, profile.crs) is True,
                f"{name}: real eligible receiver grid was not established")
    require(mask.preflight_grid(profile.bounds_wsen, 2000.0, profile.crs, max_points=9) is True,
            "The national preflight must find a receiver within nine grid probes")
    require(mask.preflight_grid(profile.bounds_wsen, 2000.0, profile.crs, max_points=1) is None,
            "An exhausted preflight limit must remain undecided, not claim an empty area")
    print("PASS empty-area preflight: three foreign rectangles rejected; Berlin land/grid "
          "distinguished; mainland, islands and exclave retained; national check bounded to nine points")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache-root", required=True, type=Path, help="Existing DOPPLERGEIST data cache")
    parser.add_argument("--online", action="store_true", help="Allow acquisition of the pinned public BKG feature")
    args = parser.parse_args(argv)
    try:
        validated = check_contracts()
        mask = check_mask(args.cache_root, args.online, validated)
        check_border_grid(mask, validated)
        check_empty_areas(mask, validated)
    except (CheckFailure, ImportError, OSError, ValueError, RuntimeError) as error:
        print(f"FAIL country verification: {error}", file=sys.stderr)
        return 1
    print("PASS geographic software checks. Not exercised: flight acquisition/association, terrain sampling, "
          "job/checkpoint resume, full refinement, or recording localization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
