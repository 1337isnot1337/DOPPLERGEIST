"""Measure full-CONUS bounded enumeration/scoring on a declared flight index.

This is a scale fixture, not an audio localization benchmark: a deterministic
analytic ridge has no assigned flight/location truth. The default coarse grid
measures resource use; it does not establish 100 m accuracy or search recall.
"""
import argparse
import json

import numpy as np

from aircraft_geoloc.audio import Spectrum
from aircraft_geoloc.data_access import CONUS, FlightIndex, write_json
from aircraft_geoloc.tiled_search import SearchBudget, search_national


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index")
    parser.add_argument("output")
    parser.add_argument("--spacing-m", type=float, default=20000)
    parser.add_argument("--tile-cells", type=int, default=4)
    args = parser.parse_args()
    from aircraft_geoloc.terrain import Terrain
    index = FlightIndex(args.index)
    start, end = index.report["coverage"]["time_range_s"]
    origin = start
    center = (end - start) / 2
    t = np.linspace(center - 20, center + 20, 41)
    ridge = 120 * (1 - .12 * np.tanh((t - center) / 12))
    spec = Spectrum(t, np.array([80., 160.]), np.zeros((2, len(t))), np.zeros((2, len(t))))
    event = {"start_s": float(t[0]), "end_s": float(t[-1]), "cpa_receive_s": center,
             "speed_range_mps": [1, 308], "slant_range_m": [1, 20000], "f0_range_hz": [50, 250]}
    budget = SearchBudget(spacing_m=args.spacing_m, tile_cells=args.tile_cells, top_k=100,
                          refine_spacing_m=args.spacing_m, max_candidates_per_tile=20000)
    report = search_national([index], Terrain(constant_m=0), [event], [(spec, ridge, np.ones(len(t)), {})],
                             time_range_s=(start, end), output_dir=args.output, bounds=CONUS, budget=budget,
                             scoring={"mode": "ridge", "time_origin": origin, "time_sweep_s": 0})
    report["experiment_scope"] = "Full CONUS all-type real flight data, analytic ridge scale fixture, constant ground, no localization truth"
    report["limitations"] = ["No automatic audio detection in this scale fixture", "No measured location accuracy",
                             "Coarse grid can miss narrow candidate modes", "Constant ground is a computational fixture"]
    write_json(str(args.output) + "/scale-report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("ranked", "coarse_ranked")}, indent=2))


if __name__ == "__main__":
    main()
