# Real audio collection and Doppler-candidate review

All new recordings in this collection were processed with the automatic audio
scanner only. No flight matching, aircraft association or geolocation was run on
the collected clips. No coordinates, flight IDs or recording windows were scanner
inputs. Downloaded media, detailed ridge outputs and review plots stay local.

The broad video survey and the smaller candidate index serve different purposes:
the survey preserves positive, negative and failed outcomes; the index collects
the strongest reviewed real-recording leads for follow-up. Neither is an accepted
aircraft-localization benchmark yet.

## Broad online-video survey

The [expanded case table](../benchmarks/youtube-expanded-scan-20261103.csv) and
[summary](../benchmarks/youtube-expanded-scan-20261103.md) contain 314 distinct
YouTube video IDs. The final per-ID outcomes are 273 successful scans, 41
unsuccessful acquisitions, 47 successful scans with moving-tone proposals and
226 successful scans with no proposals. All 47 proposal cases received a quick
single-reviewer spectrogram screen: five were labeled *candidate Doppler-like*,
five looked plausible but showed possible edits or repetition, and 37 remained
ambiguous. These labels do not confirm aircraft identity or continuous recording
time.

Successful-scan proposals by query category were:

| Search category | Scanned | With proposals |
| --- | ---: | ---: |
| Aircraft-targeted | 62 | 18 |
| Outdoor walks | 48 | 10 |
| Site-named aircraft | 26 | 8 |
| Adverse conditions | 39 | 4 |
| Birds and nature | 26 | 3 |
| Indoor | 29 | 3 |
| Phone movement | 43 | 1 |

These categories describe the searches, not verified microphones or recording
conditions. Results are query-selected, not random or representative of YouTube.
Most scans cover the first 180 seconds, or the entire source if shorter; this is
not full-video screening for long sources. The three indoor proposals were all
ambiguous. A no-proposal result applies only to the analyzed excerpt.

The original [392-source survey snapshot](../benchmarks/online-audio-survey-20261103.csv)
is retained unchanged as a historical artifact. The expanded table reconciles it
with retries and the separate site-named search, deduplicates by video ID and
preserves unsuccessful acquisition outcomes and multiple attempts.

## Candidate index

The [25-row candidate index](../benchmarks/audio-candidate-index-20261103.csv)
contains:

- **20 Eclipse Soundscapes site recordings** with a reviewed descending tonal
  band and a publisher-reported site coordinate. Two of the 20 have weak or
  interrupted visual support. The coordinate reference is kept separately in
  [the truth-separated table](../benchmarks/truth-separated/audio-candidate-location-references-20261103.csv).
  The publisher coordinate is for a deployment site; microphone placement error
  is unknown. Filename-derived times are claims, not independently verified UTC.
- **Five YouTube candidates** labeled *candidate Doppler-like* in the visual
  review. Their exact receiver coordinates are unprovided; some titles mention a
  coarse place. Aircraft identity, recording UTC and independence from editing
  are not established.

The Eclipse and YouTube candidates are real recordings and real moving-tone
evidence, but the source of the tonal bands has not been confirmed as aircraft.
The site coordinate is not a surveyed microphone coordinate. These clips are
useful candidate material for further evidence gathering; they cannot yet measure
100–1,000 m localization error. The requested **20 known-location usable aircraft
clips plus five usable unknown-location aircraft clips remains unmet** until
aircraft/source identity and the needed receiver position/time evidence are
independently established.

The candidate exporter uses only the committed scanner/review manifests and local
publisher metadata. It creates the location table separately:

```bash
python scripts/export_audio_candidate_index.py \
  --truth-root /home/cinna/.local/state/dopplergeist-eclipse-corpus-20261103 \
  --index benchmarks/audio-candidate-index-20261103.csv \
  --truth benchmarks/truth-separated/audio-candidate-location-references-20261103.csv
```

Never pass the truth-separated coordinate table into the scanner or use it to
narrow an evaluation search. The exporter does not download or rescan audio.

## Acquisition and scanner reproduction

The broad survey used the predeclared query plan
[`online-audio-search-plan-20261103.json`](../benchmarks/online-audio-search-plan-20261103.json)
and [`collect_audio_corpus.py`](../scripts/collect_audio_corpus.py). Collection
clips use the first available 180 seconds, or the full shorter source; sample
zero and upload time are not recording UTC. The collector's scanner settings are
recorded in the saved scan JSON under the local corpus roots. No source video or
audio is committed.

The expanded table can be regenerated without download or rescanning when its
six local collection roots remain available:

```bash
python scripts/export_youtube_survey_20261103.py \
  --state-root /home/cinna/.local/state \
  --output /tmp/youtube-expanded-scan-20261103.csv
```

Source rights and continued online availability are not established by this
survey. Retain failed downloads, ambiguous proposals and no-proposal excerpts in
any future update.
