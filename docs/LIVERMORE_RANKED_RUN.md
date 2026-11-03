# Livermore MP3: all-aircraft ranked run

This run uploads the same real MP3 used in the [Livermore example](LIVERMORE_DEMO.md)
to DOPPLERGEIST's local API. It detects events from the entire recording and ranks
locations against a regional index built from the **all-aircraft** ADSB.lol archive,
including jets and unknown types. The aircraft ID was not supplied to the search.

[Download all 105 ranked candidates](../benchmarks/results/livermore-all-traffic-ranked-20261103.csv).
The last CSV column is a post-run comparison to an inferred reference, not an input
to scoring. Scores rank fits; they are not probabilities. The first five raw rows
include several almost identical positions. To make alternatives easier to see,
the table below selects each successive row at least 300 m from every earlier
selected row, preserving its original rank and score.

| Original rank | Latitude | Longitude | Score | Distance to inferred reference |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 37.648049 | -121.793741 | 0.936082 | 1,982 m |
| 4 | 37.664080 | -121.787171 | 0.935408 | 477 m |
| 10 | 37.646787 | -121.789685 | 0.929479 | 1,949 m |
| 17 | 37.662932 | -121.783568 | 0.927466 | 153 m |
| 18 | 37.645785 | -121.785765 | 0.926967 | 1,965 m |

All five representatives are associated with the same archived aircraft, `aaa077`.
A post-run comparison of that aircraft's raw positions with the published N784MB
KML yielded 4.12 m median and 25.29 m maximum horizontal difference at nine
common timestamps from 17:41–17:44 UTC. This supports the association, but the
reference point was inferred from other tracks in the dataset and is **not a
surveyed microphone position**. Thus the table does not establish true location
error or independent benchmark success.

## What was searched and why it remains inconclusive

- Input: the published 85.23-second recording encoded as MP3; source recording
  [Praveen Pathak, Zenodo 23424278](https://doi.org/10.5281/zenodo.23424278), CC BY 4.0.
  The automatic pipeline discovered two acoustic groups and matched one; their
  independence is not established. No event window or band was supplied.
- Strong priors: the same approximately 10-second sample-zero window derived
  from the published ridge and recording duration; a reference-derived rectangle
  `[-121.8068757, 37.6382161, -121.7568757, 37.6882161]` in WGS84. This is a
  constrained demonstration, not a blind test.
- Flight input: ADSB.lol `v2026.05.14-planes-readsb-staging-0`, © ADSB.lol contributors, [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). The
  complete daily archive was scanned for untrimmed tracks intersecting the
  buffered bounds `[-122.5, 37.0, -121.0, 38.4]` and 17:30–18:00 UTC. The
  resulting index contained 466 aircraft, 1,086,100 rows and 5,341 gap-split
  segments. The index reports complete *declared source scope* for the requested
  search; it cannot prove receiver capture of every real aircraft.
- Search: source revision `7565d81`; 200 m coarse grid, 100 m search refinement,
  100 retained modes, five final refinement seeds, and four tile workers. All
  **4/4 tiles** were processed, covering 612 grid points and 71 refinement points;
  54 additional refinement points were skipped. The search report recorded 227.4 s
  and 499 MiB process peak RSS; these do not measure whole-job elapsed time or
  total memory across worker processes. Times are not portable performance estimates.
- Outcome: **inconclusive / search_incomplete**, with 105 ranked rows. The
  all-aircraft data scope was available, but the physical model left 98 unsupported
  CPA work evaluations across 13 track segments. Their reported failures were
  non-subsonic interpolated motion; three segments had a reported problematic
  interval overlapping the requested emission window. The remaining segments'
  reported problematic intervals were outside it, but the current implementation
  conservatively excludes their entire affected segments.
- The report also records 15,404 unclassified candidate envelopes and 266,663
  unknown clock trials. All 15,404 envelopes have score bounds, and 10,526 are
  bounded rejections; other bounds can remain competitive. Unsupported
  trajectories and unassessed alternatives therefore prevent treating the
  returned list as an exhaustive or accepted answer, even though the tile grid
  itself finished. One flyover can leave strong competing locations.

The [earlier one-aircraft upload](LIVERMORE_DEMO.md#separate-automatic-mp3-upload)
returned 105 candidates as well. Its 1,391 unknown trials were all bounded
rejections; they were not, by themselves, the missing-coverage problem. Its index
contained only the known aircraft. The full-archive run above fixes that input
scope but exposes separate trajectory-model limits.

## Reproduce the run

Install DOPPLERGEIST and FFmpeg as in the [README](../README.md). Download the
2026-05-14 archive with `scripts/fetch_adsblol_day.py`; scan it with
`scripts/ingest_adsblol_day.py` using the bounds and UTC interval above, `--keep-jets`,
and a new output filename; build an index with `scripts/index_flights.py` using
the same bounds/time and `--all-aircraft`. Configure `flight_indexes` to point
to that index and provide the validated Copernicus terrain and EGM2008 geoid.
Use the [local upload API](PRODUCT.md) with the time window and search rectangle
above. Supply neither the reference coordinate nor aircraft identity as scoring
inputs. The reference-derived rectangle itself is an explicit prior. The result
JSON contains the ordered candidates and coverage diagnostics; compare with the
inferred reference only after the search.

To export the resulting `result.json` without requiring a reference:

```bash
.venv/bin/python scripts/export_ranked_job.py path/to/job/result.json results/ranking
```

Add `--reference LAT LON` to compute an **evaluation-only** distance after the
run. The command writes the full score-ordered CSV and a second CSV of spatially
distinct representatives. `--separation-m` changes the representative spacing;
it never changes the search or its full ranking.
