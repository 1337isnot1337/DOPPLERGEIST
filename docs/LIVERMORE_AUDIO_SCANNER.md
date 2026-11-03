# Real Livermore audio scanner run

This run applies automatic whole-recording intake and Doppler-event discovery to the 40 real WAV recordings in the public [Zenodo Livermore aircraft dataset](https://zenodo.org/records/23424278). The record includes frequency-versus-time annotations and ADS-B KML tracks and is published under CC BY 4.0. The media remain outside this repository.

## Blind scan

All 40 `audio.wav` files were selected by walking the extracted record in sorted path order. Before intake, each WAV was given an opaque name derived from its SHA-256. The scanner received audio only; it was not given the case IDs, frequency traces, KML tracks, UTC metadata, coordinates, or flight labels. The run used `intake_recording` and the default `DiscoverySettings` from production source revision `3e38642`, with no historical-flight matching or geolocation.

Run command:

```bash
PYTHONPATH=src python scripts/scan_zenodo_audio_corpus.py \
  --audio-root /path/to/zenodo-23424278/extracted \
  --output-dir /path/to/zenodo-23424278/scanner-v1
```

The output directory must be empty. The compact result table `benchmarks/zenodo-livermore-scanner-v1/summary.csv` records each opaque clip hash, proposal status, ridge count, harmonic-group count, and audio metadata. Full ridge JSON stays in the local run output instead of bloating the repository. `benchmarks/truth-separated/zenodo-livermore-annotations-v1.csv` maps opaque hashes to the publisher's case IDs, annotation files, and linked track names after scanning.

## Outcome

The scan completed all 40 recordings (3,605.33 seconds total). Thirty-five produced at least one moving-tone proposal and five produced none. The outputs contain 182 ridge proposals grouped into 137 harmonic groups. These counts describe scanner output only; proposal presence does not establish an aircraft source, and a no-proposal result is a scanner miss relative to a candidate dataset, not proof that the recording has no aircraft sound.

The separate source map exists only to preserve provenance and enable later review against the publisher's frequency annotations. Its UTC and track fields were not scanner inputs. Exact recorder coordinates are not published in this record, so this is a real-audio scanner corpus, not a known-location localization benchmark. Do not count it toward the project's 20 known-location / 5 unknown-location acceptance target.

Source audio was used for discovery and remains local; it is not committed. No synthetic data was used or committed. No flight matching, location search, or threshold tuning was run. Local per-clip JSONs retain the discovered ridges and settings.
