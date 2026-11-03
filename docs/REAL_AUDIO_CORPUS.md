# Online audio collection and scanner survey

The owner's current priority is search optimization. Continue this collection in
parallel without launching geolocation or aircraft matching on its recordings.
The requested benchmark remains **20 location-known usable clips plus 5
location-unresolved usable clips**. It is not complete.

`scripts/collect_audio_corpus.py` searches public YouTube/Freesound pages, obtains
audio-only MP3 excerpts, runs the unchanged intake/discovery scanner, and exports a
single CSV retaining download failures and zero-proposal recordings. It accepts no
flight IDs, locations, frequency bands or event windows as scanner inputs.
Media, full ridges and source descriptions stay local. No source video is committed.

## Current collection

[Source and result table](../benchmarks/online-audio-survey-20261103.csv):

- 392 source records: 287 YouTube videos and 105 Freesound sounds.
- 18 YouTube excerpts scanned, totaling 45.57 minutes: 6 with moving-tone
  proposals and 12 with none. These are scanner results, not confirmed aircraft.
- 246 acquisition failures, retained separately from scanner negatives.
  Freesound preview URLs returned HTTP 403; later YouTube attempts failed with
  connection refused. The remaining 128 sources have not been scanned.
- The initial C-130 pilot excerpt also yielded zero proposals; it is separate
  from the table's 18 completed excerpts.

Queries cover targeted aircraft, outdoor walks, birds/nature, indoor recordings,
phone/movement and adverse conditions. The table records the search category;
actual equipment and environment still require source review. This is an English
search-selected sample, not a random or representative sample of YouTube.

Do not count a source as a usable benchmark merely because the scanner found a
tone. An onboard takeoff recording, for example, can contain engine-frequency
changes without representing a fixed observer hearing aircraft Doppler. Sound
effects and edited/looped ambience also require review. A zero result means the
current scanner found no qualifying proposal, not that no aircraft was audible.

Publisher map pins are labeled as such, with unknown microphone accuracy.
Upload time is not recording UTC. A source lacking independently established time
and precise location can still support acoustic tests, but cannot establish
100–1,000 m geolocation accuracy. Unknown-location clips must not be localized
as part of this collection task.

## Resume and coordination

Local corpus root:
`/home/cinna/.local/state/dopplergeist-audio-corpus-20261103`.
It contains `sources.jsonl`, `audio/`, `scans/`, `logs/`, the two search plans,
and `catalog.csv`. Decoded temporary audio is removed after scanning. The full
MP3 excerpts and measured ridges remain available to other local workers.

```bash
PYTHONPATH=src python scripts/collect_audio_corpus.py search \
  --root /path/to/corpus --plan benchmarks/online-audio-search-plan-20261103.json
PYTHONPATH=src python scripts/collect_audio_corpus.py run \
  --root /path/to/corpus --workers 2 --seconds 180
PYTHONPATH=src python scripts/collect_audio_corpus.py export --root /path/to/corpus
```

Install `requests`, the project's scanner dependencies, FFmpeg and yt-dlp.
Completed/failed sources are skipped on subsequent runs; use `--retry` to retry
failures. `--category` selects a search category. Optional `reviews.json` maps
source IDs to reviewed fields/notes, which override catalog fields on export.
Clips use the first available 180 seconds, or the complete shorter source; a live
source's relative start is not established recording UTC.

Coordinate in [Discussion 39](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39):
W1 owns the broader YouTube survey, W5 distinct known-site YouTube clips, and W4
the separate AeroSonicDB sample. Check video IDs before downloading duplicates.
Keep externally sourced media local unless redistribution permission is clear.
