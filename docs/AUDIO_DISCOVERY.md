# Automatic audio-event discovery

`discover_events(recording, output_dir=None, settings=None)` consumes the
`IntakeRecording` from intake and returns shared-contract `DetectedEvent`
dictionaries. The normal call supplies no time windows, frequency bands, aircraft
IDs, search locations or truth. It scans all decoded samples with fixed 120 s
chunks / 60 s overlap, a 2 s Hann spectrum at 0.5 s hops and 40–1600 Hz coverage
(clamped below decoded Nyquist). Working memory is bounded by chunk size; a disk
cache holds the complete recording. Inputs under one spectral window return [].

Time-whitened spectral contrast suppresses persistent stationary tones. Local
maxima are linked with bounded motion, short missing spans and local slope
continuity. Minimum duration/support, resolved downward frequency change,
distributed motion and jump checks reject noise paths and switching stationary
tones. Duplicate overlapping chunk ridges merge before grouping harmonics. Both
integer ratios and rational ratios (e.g. measured 2f and 3f with an absent
fundamental) count as one independent event. The lowest measured harmonic is the
representative ridge; no fundamental is invented. Harmonic count denotes distinct
measured ratios, including fragmented traces of the same harmonic only once.

The output preserves recording-relative ridge samples and weights, measured
window/band, harmonic-group identity, contrast/support, spectral resolution and
uncertainty diagnostics. Resolution is not a calibrated error interval; no raw
quality score is a probability. No compulsory straight-flight speed, slant or
source-frequency estimate constrains downstream search. These are **acoustic
moving-tone proposals**, with aircraft identity unconfirmed. Association must
reject unsupported proposals and count harmonic groups once.

With output_dir, discovery saves `discovery.json` (all events, settings, chunk
counts, original harmonic ridges and input hash), `discovery.png` (overview), and
per-event CSV plus spectrogram PNG. Each spectrogram image is limited to a chunk's
span; the full measured ridge remains in JSON/CSV. Existing discovery outputs
are refused. A reproducible whole-file entry point is:

```bash
PYTHONPATH=src .venv/bin/python scripts/discover_audio.py input.mp3 --output results/new-audio-scan
```

The script records source/code hashes, git state, settings, runtime and peak RSS.
It does not consume evaluation labels. Run post-hoc evaluation in a separate
process. Use a new output directory for every run.

Development evidence before DG-02 controls: full synthetic WAV (1180 s), 2
proposals spanning both planted passes, 7.24 s / 238044 KiB peak RSS; full public
reference WAV (3600.18425 s after decode), 8 proposals, 31.05 s / 249528 KiB peak
RSS. The two prominent known passes are covered, but are fragmented into multiple
proposals; the documented faint pass is missed. Six other reference proposals
are unmatched/unverified, not labelled aircraft or certified false alarms. No
complete real event annotation exists to calculate reference precision/recall.
Earlier v1/v2 diagnostics preserve a missed synthetic event and excess proposals.
These are development checks, not independent location/nationwide validation.

Known limits: fixed spectral scale and minimum duration can miss steep/short,
faint, low-frequency or high-frequency events. A single wide ridge can fragment
across missing spans, and acoustically similar harmonic sources can be grouped
ambiguously. No algorithm can establish aircraft identity solely from an arbitrary
matching synthetic chirp. The existing real recording has no independently
verified UTC clock. This implementation does not establish 100 m localization.

Focused tests: `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_discovery.py`.
They cover complete-file seams, harmonic grouping including an absent fundamental,
simultaneous unrelated events, noise/stationary/upward-sweep rejection, short
unsupported clips, and crossfading stationary tones. Fixed-setting DG-02 corpus
results are recorded separately in the audio evidence handoff.
