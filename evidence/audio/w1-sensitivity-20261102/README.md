# Global contrast sensitivity development check

Experiment code9b9dffa with global min_contrast=2.5 is equivalent to the new
default in d5de96c. No manual windows/bands, candidate positions, flight identities
or truth entered discovery. default-equivalence.json verifies identical complete
synthetic event JSON and identical configuration between experiment and default.
The committed producer and benchmark adapter remain separate from the post-run
evaluation. This is development/regression tuning, not new held-out validation.

The full1180s synthetic WAV still produces exactly2 event groups, now119–196s and
1038–1121s (earlier first ridge143–180.5s). The full reference produces16 acoustic
proposals rather than6. It includes a short1265.5–1282s ridge within the previously
missed faint passage. Only after discovery, comparison to the archived manual
measurement yields median absolute difference0.6923Hz over23 overlapping points,
90th percentile2.1394Hz. posthoc-evaluation.json records the evaluation-only
reference hash and exact comparison. This does not independently prove aircraft
identity, clock or location. The prior3.0-threshold miss and all earlier failed
or excess-proposal outputs remain under the previous versioned evidence folders.

The additional unverified proposals are a real association/search cost. A short
recovered core cannot replace weak-wing context or resolve distant alternatives
by itself. All ambiguous modes and insufficient evidence still require explicit
inconclusive outcomes. No100m or national real-localization success is claimed.

Known DG-02 regression:14 cases,8 hits,0 misses,0 false alarms,0 execution errors;
complete predictions/report are included. Its original public deterministic
held_out split is not newly held out for this development setting. The experiment
adapter is preserved, including its explicit global override, so these results
are reproducible without changing normal input contracts.

Final candidate code d5de96c passes **78 tests in110.63s** (`tests.log`):
`PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q --basetemp=results/pytest-audio-sensitivity-final`.
The earlier14-case experiment used9b9dffa with exactly the configuration now used
by default; new-default complete synthetic output equivalence is independently
asserted in default-equivalence.json. No repeat of the same expensive national
search was run by this audio worker.

After refreshing main85b1260, audio intake/discovery/matching/subset-consumer checks
pass23 tests in57.27s (`refreshed-consumer-tests.log`). The plotted observed gaps
are now broken visibly rather than connected by a line. `gap-plots/` contains
regenerated displays for the frozen3.0-threshold reference ridge data; original
plots are preserved. The focused render check passes1 test in8.62s, and the16s
missing span is visually verified. This display correction does not alter event
JSON or manufacture samples; the product's separate overlays must respect the
same missing-observation boundary.

The isolated follow-up starts from main374d1b3 with display patch7d072b5. Its first
render harness failed before product execution because pytest's custom basetemp
parent results/ did not exist. The original failure is retained. After mkdir -p
results, the same focused check with a new output path passes1 test in4.83s
(isolated-render-check.log). This was a runner setup correction, with no intake
or detection failure. Discovery settings remain frozen for the new webcam batch.
