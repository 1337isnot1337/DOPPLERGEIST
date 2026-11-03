# Full native support before historical selection

All three actual-CLI controls fail before and pass after the repair. They specify a 450 ft / 137.16 m geometric-minus-baro offset outside the retained clock/geographic bounds. The original native archive hashes remain unchanged; repeated output names fail without overwriting. The initial fixture-format error is retained separately and is not counted as a physical/production failure.

Commands: `PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q tests/test_ingest_adsblol_day.py` and `PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q --junitxml=results/w1-ingestion-support-20261103/tests.xml`. Full gate: 222 passed plus 6 subtests, 77.54 s at source 3627492, based on main ff3abc5. No historical dataset was rewritten and no new localization success is claimed.
