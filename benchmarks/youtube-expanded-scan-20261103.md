# Expanded real-video Doppler scanner survey

This is a scanner-only survey of 314 distinct YouTube video IDs. The
[case table](youtube-expanded-scan-20261103.csv) retains each source URL,
title, search category, acquisition outcomes, scanner proposal counts, audio
hashes and available visual review. The categories describe the search queries,
not independently verified recording conditions. Sources were query-selected,
not randomly sampled, and IDs can represent reuploads or edited recordings.

| Final result by video ID | Videos |
| --- | ---: |
| Scanner produced moving-tone proposals | 47 |
| Scanner produced no proposal | 226 |
| No successful acquisition | 41 |
| Total | 314 |

Among successful scans, the query categories were: aircraft-targeted 18/62
with proposals, outdoor walk 10/48, site-named aircraft 8/26, adverse conditions
4/39, bird/nature 3/26, indoor 3/29, and phone movement 1/43. These are
proposal counts, not confirmed aircraft or estimates of detection sensitivity.
Some titles describe music, moving recorders or edited audio, and a no-proposal
result is not evidence that an aircraft was present but missed.

Of the 47 proposal-bearing videos, 21 received a quick visual spectrogram
review: three were labeled plausible Doppler-like, two plausible but with
abrupt changes consistent with edits, and 16 ambiguous. The other 26 remain
unreviewed. None of the three proposals from indoor searches has an established
indoor aircraft source; all three were visually ambiguous. These results do not
show whether indoor recording, a phone, or poor audio quality succeeds or fails.

Most scans cover the first 180 seconds, or the full video when shorter. Decoded
durations ranged from 12.54 to 180.01 seconds; this is not an analysis of entire
long videos. The shared automatic scanner used 4 kHz audio, 40–1600 Hz frequency
range and a 12-second minimum event duration. No flight matching, geolocation,
known flight IDs, recording coordinates, or truth-derived search bounds were
used. Scanner proposals do not establish aircraft identity, independent events,
source location, or recording UTC. These cases therefore do not yet satisfy the
requested 20 precisely known-location and five validated unknown-location clips.

The broad queue combined 287 preselected IDs with 29 separately selected
site-named IDs; two IDs occur in both. Two concurrent retries overlapped and
were stopped; subsequent retries used only IDs lacking a successful scan. The
case table deduplicates by ID while retaining all recorded attempt roots and
statuses. Thirty-one IDs had multiple successful scans; their proposal counts
agreed. Two of these IDs had different MP3 hashes despite matching decoded
lengths and counts; both hashes are retained and no bit-identical replay is
claimed. The earlier [site-named case table](site-leads-real-scan-20261103.csv)
contains further location references and review details. The original 41
unsuccessful final outcomes must not be treated as negative scans.

All recordings, detailed scanner outputs and review plots remain under the six
local `dopplergeist-*20261103` directories listed in the table's `attempt_roots`;
no media is committed. Original source rights and continued availability are not
established. With those preserved directories available, regenerate the table:

```sh
python scripts/export_youtube_survey_20261103.py \
  --state-root /home/cinna/.local/state \
  --output /tmp/youtube-expanded-scan-20261103.csv
```

The script hashes local audio and reconciles saved outputs; it does not download
or rescan. The collector `scripts/collect_audio_corpus.py` can perform a new
scanner-only run, but changed or removed online sources may yield different audio.
