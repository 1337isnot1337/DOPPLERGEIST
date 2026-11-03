# Fixed-seed YouTube scanner-only sample — 2026-11-03

This experiment ran the automatic audio scanner on a fixed-seed random sample
from the query-derived YouTube catalog. It did not perform flight matching,
aircraft association or geolocation.

## Outcomes

The sample contains 200 videos selected without replacement (seed `20261103`)
from 287 eligible rows in a 392-row search catalog. The collector requested up
to the first 180 seconds of audio for each video.

| Search category | Selected | Scanned | Download failures | Clips with scanner proposals | Ridge proposals |
| --- | ---: | ---: | ---: | ---: | ---: |
| Adverse conditions | 34 | 34 | 0 | 3 | 38 |
| Aircraft targeted | 40 | 39 | 1 | 9 | 46 |
| Birds and nature | 27 | 26 | 1 | 0 | 0 |
| Indoor | 31 | 31 | 0 | 3 | 16 |
| Outdoor walks | 36 | 36 | 0 | 7 | 15 |
| Phone movement | 32 | 32 | 0 | 2 | 3 |
| **Total** | **200** | **198** | **2** | **24** | **118** |

174 scanned excerpts had no scanner proposal. The 24 proposal-bearing excerpts
were visually reviewed for trace shape. That review can describe visible
descending or fragmented traces, but it cannot establish that a source was an
aircraft. Some proposal sets may contain harmonics, overlapping sources,
stationary tones, motion artifacts or other false detections. Indoor and
handheld proposals are especially inconclusive. A no-proposal result covers
only the requested excerpt; the rest of each longer video was not scanned.

The sample is random only within the query-derived catalog, not across YouTube.
Video locations and recording times were not established for these clips. None
counts toward the known-microphone or unknown-microphone localization benchmark.
The scan results preserve failed downloads and no-proposal cases instead of
dropping them. The median scan runtime was 13.019 s and the 90th percentile was
22.76 s over the 198 successful scans.

## Files

- [Per-video results](youtube-random-sample-20261103.csv) contain source URL,
  title, category, scanner outcome, proposal count, review status and excerpt
  duration.
- [Machine-readable summary](youtube-random-sample-summary-20261103.json)
  preserves the sample seed, selection counts, scanner outcomes and limits.
- [Visual review notes](youtube-random-sample-review-20261103.md) summarize
  trace-shape observations for the 24 proposal-bearing excerpts.

Downloaded media, scanner artifacts and detailed logs remain in local state;
none are committed. Online availability and source redistribution rights were
not established by this experiment.
