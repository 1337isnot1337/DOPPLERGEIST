"""Physical support and preservation controls for the optional fixture variant."""
import importlib.util
import json
from pathlib import Path
import shutil
import struct

import numpy as np
import pandas as pd
import pytest
import soundfile as sf

from aircraft_geoloc.geometry import Track, velocity_ecef


ROOT = Path(__file__).parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


GEN = module("full_support_generator", "make_multi_event_case.py")
UPLOAD = module("full_support_indexer", "ci_upload_replay.py")


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp("full-support-fixture")
    local, full = root / "local", root / "full"
    old = GEN.generate(local, 3, 20261103)
    extended = GEN.generate(full, 3, 20261103, "full-coverage")
    return local, full, old, extended


def track_from_frame(identity, frame):
    velocity = velocity_ecef(frame.lat, frame.lon, frame.east_mps, frame.north_mps, frame.up_mps)
    return Track(str(identity), frame.time_s, frame.lat, frame.lon, frame.alt_m, velocity=velocity)


def wav_without_peak_timestamp(path):
    """Ignore only libsndfile's wall-clock PEAK metadata, without changing files."""
    data = bytearray(path.read_bytes())
    offset, timestamps = 12, 0
    while offset + 8 <= len(data):
        name, size = struct.unpack_from("<4sI", data, offset)
        if name == b"PEAK":
            assert size >= 8
            data[offset + 12:offset + 16] = b"\0" * 4
            timestamps += 1
        offset += 8 + size + (size % 2)
    assert timestamps == 1
    return bytes(data)


def test_added_support_preserves_audio_labels_ids_and_every_original_observation(generated):
    local, full, old, extended = generated
    assert old["fixture_variant"] == "local-segments"
    assert old["trajectory_support"] is None
    for name in ("inputs/recording.mp3", "truth/labels.json",
                 "inputs/request.json", "inputs/terrain.tif", "inputs/geoid.tif"):
        assert (local / name).read_bytes() == (full / name).read_bytes(), name
    old_wav, full_wav = local / "renderer/recording.wav", full / "renderer/recording.wav"
    assert wav_without_peak_timestamp(old_wav) == wav_without_peak_timestamp(full_wav)
    for path in (old_wav, full_wav):
        info = sf.info(path)
        assert (info.samplerate, info.frames, info.channels, info.subtype) == (GEN.RATE, 740 * GEN.RATE, 1, "FLOAT")
    original = pd.read_parquet(local / "inputs/tracks.parquet")
    expanded = pd.read_parquet(full / "inputs/tracks.parquet")
    assert set(original.flight_id) == set(expanded.flight_id)
    for identity, core in original.groupby("flight_id", sort=False):
        matching = expanded.loc[(expanded.flight_id == identity) & expanded.time_s.isin(core.time_s)]
        pd.testing.assert_frame_equal(core.reset_index(drop=True), matching.reset_index(drop=True), check_exact=True)
    assert original.groupby("flight_id").size().tolist() == [271] * 9
    assert expanded.groupby("flight_id").size().tolist() == [1854] * 9
    assert extended["trajectory_support"]["original_rows_preserved"] is True


@pytest.mark.parametrize("events,padding,samples", ((3, 813, 1854), (4, 963, 2224), (6, 1264, 2965)))
def test_support_bound_is_predeclared_and_covers_slowest_sound_speed(events, padding, samples):
    plan = GEN.full_support_plan(220 * events + 80)
    assert plan["left_padding_s"] == padding
    assert plan["emission_interval_s"][1] - plan["emission_interval_s"][0] + 1 == samples
    assert plan["start_arrival_upper_bound_s"] < GEN.EPOCH
    assert plan["end_arrival_lower_bound_s"] > GEN.EPOCH + 220 * events + 80
    assert plan["minimum_sound_speed_mps"] == 338
    assert 0 < plan["arrival_monotonicity_lower_bound"] < 1


def test_speed_certificate_detects_velocity_between_samples():
    # p(0)=0, p(1)=1 and endpoint derivatives -1 give p'(1/2)=2.
    # Its middle Bezier velocity control is 5, so endpoint speed alone fails.
    bound = GEN.hermite_speed_control_bound(np.array([0., 1.]),
        np.array([[0., 0., 0.], [1., 0., 0.]]), np.array([[-1., 0., 0.], [-1., 0., 0.]]))
    assert bound == 5


def test_serialized_tracks_have_continuous_joins_bounded_speed_and_acoustic_support(generated):
    local, full, _, manifest = generated
    original = pd.read_parquet(local / "inputs/tracks.parquet")
    expanded = pd.read_parquet(full / "inputs/tracks.parquet")
    certificate = manifest["trajectory_support"]
    receive = np.linspace(GEN.EPOCH, GEN.EPOCH + 740, 31)
    for identity, frame in expanded.groupby("flight_id", sort=False):
        track = track_from_frame(identity, frame)
        old = original.loc[original.flight_id == identity]
        core = track_from_frame(identity, old)
        lower = int(core.time[0] - track.time[0])
        np.testing.assert_array_equal(track.spline.c[:, lower:lower + len(core.time) - 1], core.spline.c)
        velocity = track.speed_vector(track.time)
        dt = np.diff(track.time)
        middle = 3 * np.diff(track.xyz, axis=0) / dt[:, None] - velocity[:-1] - velocity[1:]
        assert max(np.linalg.norm(velocity, axis=1).max(), np.linalg.norm(middle, axis=1).max()) < certificate["speed_bound_mps"]
        assert frame.alt_m.min() > GEN.GROUND and frame.alt_m.max() < 20000
        for index in (0, len(track.time) // 2, len(track.time) - 1):
            observer = track.xyz[index] + np.array([GEN.MAX_CANDIDATE_RANGE_M, 0, 0])
            for sound in (338., 343., 348.):
                assert track.time[0] + np.linalg.norm(track.xyz[0] - observer) / sound < receive[0]
                assert track.time[-1] + np.linalg.norm(track.xyz[-1] - observer) / sound > receive[-1]
                factor, emission, distance = track.acoustic(receive, observer, sound)
                assert np.isfinite(np.column_stack((factor, emission, distance))).all()
    assert max(item["tangent_position_roundtrip_error_m"] for row in certificate["tracks"]
               for item in row["joins"]) <= 1e-6
    assert max(item["velocity_roundtrip_error_mps"] for row in certificate["tracks"]
               for item in row["joins"]) <= 1e-8


@pytest.mark.parametrize("defect", ("missing_sample", "changed_core", "unsafe_speed", "below_ground"))
def test_full_coverage_certificate_rejects_missing_or_invalid_observations(generated, defect):
    local, full, _, _ = generated
    original = pd.read_parquet(local / "inputs/tracks.parquet")
    expanded = pd.read_parquet(full / "inputs/tracks.parquet")
    if defect == "missing_sample":
        expanded = expanded.iloc[1:].copy()
    elif defect == "changed_core":
        index = expanded.index[(expanded.flight_id == original.flight_id.iloc[0])
            & (expanded.time_s == original.time_s.iloc[0])][0]
        expanded.loc[index, "lat"] += 0.001
    elif defect == "unsafe_speed":
        expanded.loc[0, "east_mps"] = 500
    else:
        expanded.loc[0, "alt_m"] = GEN.GROUND
    with pytest.raises(ValueError):
        GEN.certify_full_coverage(expanded, original, GEN.full_support_plan(740))


def index_inputs(tmp_path, source):
    inputs, evaluation = tmp_path / "inputs", tmp_path / "evaluation"
    inputs.mkdir()
    evaluation.mkdir()
    for name in ("tracks.parquet", "coverage.json"):
        shutil.copy2(source / "inputs" / name, inputs / name)
    return inputs, evaluation


def test_full_coverage_index_preserves_every_aircraft_and_sample(generated, tmp_path):
    _, full, _, _ = generated
    inputs, evaluation = index_inputs(tmp_path, full)
    UPLOAD.index_fixture(inputs, evaluation, tmp_path / "flights.sqlite", tmp_path / "index.json", 3, "full-coverage")
    report = json.loads((tmp_path / "index.json").read_text())
    assert report["fixture_variant"] == "full-coverage"
    assert report["tracks"] == 9 and report["rows"] == 16686
    assert set(report["rows_per_track"].values()) == {1854}
    assert report["typecode_rows"] == {"C172": 5562, "PC12": 5562, "A320": 5562}
    assert report["all_rows_retained"] and report["all_non_id_values_preserved"]
    mapping = json.loads((evaluation / "flight-id-mapping.json").read_text())["original_to_opaque"]
    inverse = {value: key for key, value in mapping.items()}
    before = pd.read_parquet(evaluation / "original-tracks.parquet")
    after = pd.read_parquet(inputs / "tracks.parquet")
    after["flight_id"] = after.flight_id.map(inverse)
    pd.testing.assert_frame_equal(before.sort_values(["flight_id", "time_s"]).reset_index(drop=True),
        after.sort_values(["flight_id", "time_s"]).reset_index(drop=True), check_exact=True)


@pytest.mark.parametrize("defect", ("legacy_mode", "shifted_sample", "missing_aircraft", "missing_certificate"))
def test_extended_index_rejects_undeclared_or_incomplete_fixture(generated, tmp_path, defect):
    _, full, _, _ = generated
    inputs, evaluation = index_inputs(tmp_path, full)
    frame = pd.read_parquet(inputs / "tracks.parquet")
    if defect == "shifted_sample":
        frame.loc[0, "time_s"] += 0.25
        frame.to_parquet(inputs / "tracks.parquet", index=False)
    elif defect == "missing_aircraft":
        frame.loc[frame.flight_id != frame.flight_id.iloc[0]].to_parquet(inputs / "tracks.parquet", index=False)
    elif defect == "missing_certificate":
        coverage = json.loads((inputs / "coverage.json").read_text())
        del coverage["trajectory_support"]
        (inputs / "coverage.json").write_text(json.dumps(coverage))
    with pytest.raises(ValueError):
        UPLOAD.index_fixture(inputs, evaluation, tmp_path / "flights.sqlite", tmp_path / "index.json", 3,
            "local-segments" if defect == "legacy_mode" else "full-coverage")
