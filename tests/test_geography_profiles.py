from dopplergeist.geography import profile_for_search, public_profiles, receiver_mask_for_search


def test_spain_profile_supports_bounded_madrid_uploads_without_germany_mask(tmp_path):
    search = {"country": "ES", "coverage": "spain",
              "bounds_wsen": [-4.16, 40.05, -2.97, 40.95]}
    profile = profile_for_search(search)

    assert profile.country == "ES"
    assert profile.coverage == "spain"
    assert profile.crs == "EPSG:6933"
    assert profile.bounds_wsen == (-18.2, 27.5, 4.5, 43.9)
    assert receiver_mask_for_search(search, cache_root=tmp_path, offline=True) is None


def test_spain_profile_is_available_to_upload_capabilities():
    profile = next(item for item in public_profiles() if item["country"] == "ES")

    assert profile["coverage"] == "spain"
    assert profile["name"] == "Spain (all territories; bounding envelope)"
    assert profile["bounds_wsen"] == [-18.2, 27.5, 4.5, 43.9]


def test_norway_profile_supports_bounded_oslo_uploads_without_country_mask(tmp_path):
    search = {"country": "NO", "coverage": "norway", "bounds_wsen": [10.6, 59.85, 10.9, 60.0]}
    profile = profile_for_search(search)

    assert profile.country == "NO"
    assert profile.coverage == "norway"
    assert profile.crs == "EPSG:3035"
    assert profile.bounds_wsen == (4.0, 57.9, 31.2, 71.2)
    assert receiver_mask_for_search(search, cache_root=tmp_path, offline=True) is None


def test_norway_profile_is_available_to_upload_capabilities():
    profile = next(item for item in public_profiles() if item["country"] == "NO")

    assert profile["coverage"] == "norway"
    assert profile["name"] == "Norway (mainland; bounding envelope)"
    assert profile["bounds_wsen"] == [4.0, 57.9, 31.2, 71.2]
