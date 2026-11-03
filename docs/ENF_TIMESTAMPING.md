# ENF timestamp recovery: research status

Electrical Network Frequency (ENF) may provide recording-time evidence when a
real mains-related signal is captured in the audio and a matching, timestamped
grid reference exists. A stationary 50/60 Hz tone by itself is not enough: fans,
power supplies, motors and other equipment can produce similar tones. ENF
cannot be reported as a timestamp until the extracted frequency variation has
been matched to an independent reference and ambiguity and clock drift have
been assessed.

## Current prototype

[`scripts/scan_enf_signal.py`](../scripts/scan_enf_signal.py) screens real audio
for peaks near 50/60 Hz and their first three harmonics. It reports per-window
frequency estimates, local spectral prominence and coverage in a new output
directory. It does **not** identify grid hum, compare a historical reference,
estimate UTC, infer a location, or alter the aircraft search request. A strong
screen result is only a reason to investigate the trace further.

Example for a new output directory:

```bash
python scripts/scan_enf_signal.py recording.mp3 \
  --output-dir results/enf-screening-v1
```

The default uses the same 4 kHz mono decoding path already used by DOPPLERGEIST.
The 4-second window and 1-second hop are screening settings, not a calibrated
ENF extractor. A future timestamp estimator needs longer-window and
multi-harmonic comparisons against real references, plus held-out tests.

## First real-audio screen (2026-11-03)

The prototype screened 50 real recordings at 4 kHz: 24 files from the
publisher-site-labelled corpus, 5 videos without an exact microphone point, 20
AeroSonic recordings, and the active one-hour upload. The site labels are not
independent recording-time evidence. The scanner did not read truth-coordinate
files or pass any result into aircraft search.

For this exploratory summary, a *persistent tone candidate* means at least
one of the six 50/60 Hz harmonic bands had local prominence of at least 10 dB
in at least 80% of its complete 4-second windows (1-second hop). This is only
a spectral peak threshold; it does not distinguish grid frequency from a
motor, power supply, interference or other sound.

| Real-audio group | Recordings | Persistent tone candidate | Two harmonics at one nominal base |
| --- | ---: | ---: | ---: |
| Publisher-site-labelled corpus | 24 | 2 | 0 |
| Unknown exact microphone point | 5 | 0 | 0 |
| AeroSonic recordings | 20 | 0 | 0 |
| Active one-hour upload | 1 | 0 | 0 |

The two single-band candidates were `site-914.mp3` (50 Hz fundamental and a
separate 120 Hz band) and `site-919.mp3` (50 Hz fundamental). Neither showed a
second persistent harmonic at the same 50/60 Hz base. The one-hour upload had
no band meeting the persistence threshold. No reference matching or UTC
estimate was attempted. These results show only that isolated narrowband tones
are uncommon under this screening rule; they do not establish ENF availability
or timestamp recovery rates.

Full per-window traces, summaries and SHA-256 receipts are preserved locally
at `/home/cinna/.local/state/dopplergeist-enf-screening-20261103/corpus-v1`.
The recordings and their local paths are not included in the repository.

## Reference-data audit

- The official [FNET/GridEye real-time display](https://fnetpublic.utk.edu/frequencygauge.html)
  describes its live plot as real-time frequency measurements.
- The FNET [table display](https://fnetpublic.utk.edu/tabledisplay.html) warns
  that displayed frequency values are sample data, not current grid
  measurements, and that actual values have been hidden from that display
  since 2018.
- [OpenENF](https://github.com/openenf/openenf) documents public references for
  parts of Europe and says public North American reference data is unavailable.
- [nate-griff/enf](https://github.com/nate-griff/enf) is a useful implementation
  reference. Its README describes QIFFT harmonic extraction and FFT-accelerated
  sliding correlation, but labels the tool an investigative aid rather than a
  proof system. Its documented collector captures the current FNET chart, and
  its checked-in daily CSVs cover 2026-03-20 through 2026-05-12. That archive
  cannot match the active 2026-09-08 upload.
- A 2025 ENF extraction evaluation reports that target duration, reference
  duration and signal-to-noise ratio affect timestamp accuracy: [Maiberger,
  Gusakov and Routtenberg, CISS 2025](https://doi.org/10.1109/CISS64860.2025.10944719).

FNET can support building a prospective archive by collecting its real-time
charts, but this does not create historical references for past recordings.
The repository's image-derived reference series also needs independent
validation of sampling cadence, frequency calibration, missing-data handling
and redistribution terms before it can be used for an accepted timestamp.

## Integration gate

Only consider passing an ENF-derived time window into the existing aircraft
pipeline after real recordings with independently established sample-zero UTC
have been matched to a genuine historical grid reference. Keep extraction
quality, reference provenance, clock-rate drift, alternative timestamp peaks
and match separation in the result. A missing reference, absent harmonic,
non-unique peak, clock drift outside tolerance or weak audio must return the
existing `needs_input`/inconclusive path. ENF region identification is at most
coarse interconnection evidence; it is not an observer coordinate.

The initial screen must run on DOPPLERGEIST's real audio only. Do not synthesize
hum, fill missing reference intervals, tune the matcher on the recording under
evaluation, or feed recording truth into extraction or reference search.
