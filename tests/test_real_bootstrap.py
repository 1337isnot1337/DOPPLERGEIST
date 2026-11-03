"""Bootstrap validation against the original MP3 and historical flight data."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path

import pytest

from dopplergeist.bootstrap import validate_bootstrap
from dopplergeist.data_access import CachedTerrain, DataUnavailable, FlightIndex, content_hash
from dopplergeist.matching import prepare_events
from dopplergeist.tiled_search import SearchBudget


@pytest.fixture(scope="module")
def real_inputs():
    job, cache, source = (os.environ.get(key) for key in
                          ("DOPPLERGEIST_REAL_JOB_ROOT", "DOPPLERGEIST_REAL_CACHE_ROOT",
                           "DOPPLERGEIST_REAL_BOOTSTRAP_INPUT"))
    if not all((job, cache, source)):
        pytest.skip("set the real job, cache and bootstrap witness paths")
    job, cache = Path(job), Path(cache)
    config = json.loads((job / "search/manifest.json").read_text())["configuration"]
    events, measurements = prepare_events(json.loads((job / "discovery/discovery.json").read_text())["events"])
    indexes = [FlightIndex(cache / "flights" / day / "staging-0/all-types-v2-543f483cee75.sqlite")
               for day in ("2026-09-08", "2026-09-09")]
    params = dict(config["scoring"])
    window = params.pop("recording_start_window_s")
    terrain = CachedTerrain(cache / "terrain", offline=True, adopt_existing=True)
    return (json.loads(Path(source).read_text()), indexes, terrain, events, measurements, config["bounds"],
            config["time_range_s"], SearchBudget(**config["budget"]), params, config["filters"],
            window, config["crs"])


def test_real_bootstrap_witnesses_and_independent_receipt(real_inputs):
    document, *arguments = real_inputs
    evidence = validate_bootstrap(document, *arguments)
    assert len(evidence["witnesses"]) == 100 and evidence["score_floor"] > 1.0
    assert all(item["score_with_floor"] >= evidence["score_floor"] for item in evidence["witnesses"])
    verifier_path = Path(__file__).resolve().parents[1] / "scripts/verify_upload_http.py"
    spec = importlib.util.spec_from_file_location("upload_verifier_bootstrap", verifier_path)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    summary = {"input_hash": content_hash(document), "evidence_hash": content_hash(evidence),
               "score_floor": evidence["score_floor"], "witness_count": 100,
               "terrain_files": evidence["terrain_files"], "terrain_ocean_tiles": evidence["terrain_ocean_tiles"]}
    configuration = {"bootstrap": summary, "budget": {"top_k": 100}}
    finite = {"bootstrap": dict(summary, input_artifact="bootstrap.json", evidence_artifact="bootstrap-evidence.json")}
    assert verifier.valid_bootstrap_evidence(configuration, finite, document, evidence)
    bad = deepcopy(evidence)
    bad["witnesses"][1]["witness"] = deepcopy(bad["witnesses"][0]["witness"])
    configuration["bootstrap"]["evidence_hash"] = content_hash(bad)
    finite["bootstrap"]["evidence_hash"] = content_hash(bad)
    assert not verifier.valid_bootstrap_evidence(configuration, finite, document, bad)


def test_bad_real_witnesses_fail_closed(real_inputs):
    document, *arguments = real_inputs
    bad = deepcopy(document)
    bad["witnesses"][0]["position_m"][0] += 1
    with pytest.raises(DataUnavailable, match="coarse grid"):
        validate_bootstrap(bad, *arguments)
    bad = deepcopy(document)
    bad["witnesses"][1] = deepcopy(bad["witnesses"][0])
    with pytest.raises(DataUnavailable, match="duplicate"):
        validate_bootstrap(bad, *arguments)


def test_real_multi_event_witnesses_with_singleton_filter(real_inputs):
    document, indexes, terrain, events, measurements, bounds, time_range, budget, params, filters, window, crs = real_inputs
    selected = [witness for witness in document['witnesses'] if len(witness['event_indices']) >= 2][:10]
    assert len(selected) == 10
    document = {'schema_version': 1, 'witnesses': selected}
    evidence = validate_bootstrap(document, indexes, terrain, events, measurements, bounds, time_range,
                                  replace(budget, top_k=10), params, dict(filters, min_events=2), window, crs)
    assert len(evidence['witnesses']) == 10
    assert all(item['score_with_floor'] == item['score'] for item in evidence['witnesses'])


def test_real_bootstrap_search_and_resume_preserve_top_modes(real_inputs, tmp_path, monkeypatch):
    from pyproj import Transformer
    from dopplergeist.data_access import write_json
    from dopplergeist import tiled_search
    from dopplergeist.tiled_search import search_national

    document, indexes, terrain, events, measurements, _, time_range, budget, params, filters, window, crs = real_inputs
    grouped = {}
    for witness in document["witnesses"]:
        grouped.setdefault(tuple(witness["position_m"]), []).append(witness)
    position, witnesses = next((position, values[:2]) for position, values in grouped.items() if len(values) >= 2)
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(*position)
    bounds = [lon-.0001, lat-.0001, lon+.0001, lat+.0001]
    budget = replace(budget, top_k=2, tile_cells=1, refine_spacing_m=budget.spacing_m, max_tiles=None)
    scoring = dict(params, recording_start_window_s=window)
    seed = {"schema_version": 1, "witnesses": witnesses}

    def run(name):
        return search_national(indexes, terrain, events, measurements, time_range_s=time_range,
                               output_dir=tmp_path/name, bounds=bounds, budget=budget, scoring=scoring,
                               filters=filters, crs=crs, workers=1)

    baseline = run("baseline")
    (tmp_path/"seeded").mkdir()
    write_json(tmp_path/"seeded/bootstrap.json", seed)
    accelerated = run("seeded")
    assert baseline["ranked"] and baseline["ranked"] == accelerated["ranked"]
    assert accelerated["finite_search_evidence"]["bootstrap"]["witness_count"] == 2
    resumed = run("seeded")
    assert resumed["ranked"] == accelerated["ranked"] and resumed["tiles_resumed"] > 0
    assert resumed["ground_truth_used_by_search"] is None
    with monkeypatch.context() as fault:
        fault.setattr(tiled_search, "_retained_score_floor", lambda *args: None)
        guarded = run("seeded")
    assert guarded["status"] == "partial"
    assert "did not retain enough assessed" in guarded["refinement_failure"]
    bad = deepcopy(seed)
    bad["witnesses"][0]["position_m"][0] += 1
    write_json(tmp_path/"seeded/bootstrap.json", bad)
    with pytest.raises(DataUnavailable, match="coarse grid"):
        run("seeded")
