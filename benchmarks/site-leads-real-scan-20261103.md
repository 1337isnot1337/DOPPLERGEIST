# Real site-named video leads: scanner outcomes

These 29 videos were preselected from uploader descriptions naming locations
near airports. A title is a lead, not proof of the microphone's position: none
of these 29 cases has independently established recorder coordinates or a
recording-start UTC uncertainty. They are therefore **not yet verified
known-location clips** and are not a location-accuracy benchmark. The source
links and relevant site references are in the [case table](site-leads-real-scan-20261103.csv).

The initial W5 scanner-only run scanned 18 first-three-minute excerpts and
recorded 11 acquisition failures. The 11 failed IDs were subsequently retried
in a separate directory; ten scanned and one video was reported unavailable.
Across the final per-source outcomes:

| Outcome | Videos |
| --- | ---: |
| Scanner produced one or more moving-tone proposals | 9 |
| Scanner produced no proposal | 19 |
| Download failed | 1 |

A quick 0–1 kHz spectrogram review found three videos with plausible descending
traces and six with ambiguous proposals. Two of the three plausible examples
show abrupt audio changes consistent with edits, so their multiple event times
must not be treated as a locked recording clock without further evidence. One
LAX excerpt produced 13 scanner group IDs in a short interval; these are not
established as 13 independent aircraft. No-proposal means only that the
scanner found no qualifying trace in that excerpt. The videos were selected by
search queries and site titles, not at random, and do not establish a general
success or false-positive rate.

The table preserves both the initial and retry outcomes, video/source URLs,
site-name references, scanner counts, MP3 SHA-256 hashes and review notes. Two
IDs overlap a separate broad YouTube survey; do not double-count them when
combining samples. Original metadata, audio, scanner output and review plots
remain local in `/home/cinna/.local/state/dopplergeist-w5-youtube-survey-20261103/`
and `/home/cinna/.local/state/dopplergeist-w4-w5-retry-20261103/`. No media is
committed. Videos may be edited or unavailable; YouTube upload date is not
recording UTC.

For a new local scanner-only replay, build a source list from the published table
and use the existing collector. This downloads audio only and passes no known
flight IDs, location coordinates, event windows or frequency bands to discovery:

```sh
DG_SITE_ROOT=/path/to/new-site-scan
mkdir -p "$DG_SITE_ROOT"
python - "$DG_SITE_ROOT" <<'PY'
import csv, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
with open('benchmarks/site-leads-real-scan-20261103.csv', newline='') as stream:
    rows = list(csv.DictReader(stream))
with (root / 'sources.jsonl').open('x') as output:
    for row in rows:
        source = {'id': 'yt-' + row['id'], 'source': 'youtube', 'url': row['url'],
                  'title': row['title'], 'category': 'site_named_aircraft',
                  'location_status': 'unresolved', 'recording_clock_status': 'not_established'}
        output.write(json.dumps(source) + '\n')
PY
PYTHONPATH=src python scripts/collect_audio_corpus.py run --root "$DG_SITE_ROOT" \
  --workers 2 --seconds 180 --download-timeout 120 --scan-timeout 180
```

The scanner inputs were selected without known flight IDs or search bounds; no
matching or geolocation was run on these recordings. Replaying a changed or
removed video may produce a different outcome. Respect each source's rights
and keep downloaded media local unless redistribution is authorized.
