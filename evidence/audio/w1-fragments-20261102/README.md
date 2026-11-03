# Conservative fragment continuation

Audio code `9b9dffa`; integrated source `0a73cf4` includes current main. This is a
follow-up to frozen discovery `4a49646`, not a rewrite of its preserved outcomes.

Full reference scan: 6 acoustic proposals (previously8). The two prominent passes
join over2091.5–2178s and3041.5–3091.5s. Maximum observed gaps remain4.5s and16s.
Four other proposals remain unverified; faint1250–1310s is still missed. No known
windows/bands, flight IDs, coordinates or truth enter discovery. The observed
ridge samples are not filled across gaps; accepted and ambiguous links are saved
in reference-discovery/discovery.json. Reciprocal uniqueness does not establish
flight identity. This scan took77.087s while the full test suite and regressions
ran concurrently, so it is not a comparable performance improvement claim.

The same14 public DG-02 controls were rerun **as regressions**, since the earlier
results are known. Report:8 hits,0 misses,0 false alarms,0 processing failures.
Every case used one identical intake/discovery/contracts source-hash set (saved
in dg02-provenance.json). No eligible location cases or localization occurred.
The earlier frozen held_out result is under w1-20261102, separate from this run.

`tests.log`:78 passed in96.17s. Exact command:
`PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q --basetemp=results/pytest-fragment-integration-9b9dffa`.
Eight dedicated discovery checks include a simulated interrupted pass with an
explicit assertion that the gap has no invented observations, ambiguous
continuations, a gap beyond the allowed bound, and all prior audio controls.

`hermes-tests.log`: the user-supplied MIT reference at pinned2c3ed20577bcce29058d73422dd4f85392d04c24
passes its6 tests in19.64s. See docs/HERMES_REFERENCE.md for scope and source links.
No donor code copied. This is not evidence of automatic national localization.

The spectral diagnostic is exposed under canonical frequency_sigma_hz plus the
compatibility frequency_uncertainty_hz key. Despite the field name, the value is
an uncalibrated robust loss scale/resolution diagnostic, not a probability or a
calibrated error interval. Matching applies its documented minimum loss scale.
