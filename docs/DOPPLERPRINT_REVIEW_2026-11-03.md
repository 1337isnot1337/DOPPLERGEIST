# Dopplerprint comparison (November 3, 2026)

Reviewed [Hexay/dopplerprint](https://github.com/Hexay/dopplerprint) at
[`964180276409998a3b9a56bc1d50e0805415e492`](https://github.com/Hexay/dopplerprint/tree/964180276409998a3b9a56bc1d50e0805415e492).
It is MIT-licensed research software with a Rust core, Python bindings and a
CLI. Its analysis documents a comparison with an older DOPPLERGEIST revision;
that comparison predates our parallel search and subsequent acoustic screens.

## What it adds

- **Audio frontend:** native decoding, multiresolution log-frequency
  spectrograms, lower-quantile temporal whitening, harmonic-comb tracking and
  uncertainty-expanded constant-velocity fits. These are promising detection
  and ranking ideas, but their recall and false-positive rates need blind
  real-recording comparisons before replacing our detector.
- **Search implementation:** Rust/Rayon cell scoring, compact flight storage,
  a 200 m to 25 m regional grid and harmonic spectrogram scoring. Its
  [profiling notes](https://github.com/Hexay/dopplerprint/blob/964180276409998a3b9a56bc1d50e0805415e492/docs/research/profiling_2026-11-03.md)
  report a large reduction in *its own* detector runtime after caching stitch
  fits. Its regional search uses a different score and assumptions; do not
  infer a nationwide speedup or numerical parity from the language choice.
- **Product:** standalone HTML, GeoJSON and GeoPackage/QGIS outputs, native
  audio decoding, and a user-configurable cache limit are useful product ideas.

## Limits relevant to our full-day run

The current `locate` workflow requires an approximate location and a start-time
prior. It associates every detected event with a distinct flight. Its
[association code](https://github.com/Hexay/dopplerprint/blob/964180276409998a3b9a56bc1d50e0805415e492/crates/dp-core/src/search/hypothesis.rs)
uses fitted speed/distance bands and stops after 64 hypotheses per cell by
default; that cap can omit candidates without the explicit incomplete-work
accounting used by our search. The silence penalty is a simple count-based
heuristic. Do not substitute these defaults for the present all-type, unknown-
clock, whole-recording run without measuring false exclusions.

The README's 40-recording Livermore figures are development results with
supplied flyover information. Its [corpus builder](https://github.com/Hexay/dopplerprint/blob/964180276409998a3b9a56bc1d50e0805415e492/tools/corpus/livermore.py)
states that recorder coordinates were not published and derives a reference
position from the same flight tracks and published distance estimates. Its
[evaluation adapter](https://github.com/Hexay/dopplerprint/blob/964180276409998a3b9a56bc1d50e0805415e492/crates/dp-core/src/eval/livermore.rs)
aligns the recording clock using a published ridge and uses the known flight to
set up the event. These results are not independent blind-localization accuracy.

The Oyster Bay case is assembled from DOPPLERGEIST's own release assets, and
its reported 79 m is relative to an approximate public reference rather than a
surveyed microphone coordinate. It is useful cross-implementation evidence,
not an independent reference for our upload. The creator's companion video and
our existing `data/source/true_camera.png` show a visual Street View match;
keep that reference separate from blind search inputs.

## Blind detector check on the original upload

The published `dopplerprint==0.1.0` wheel was installed in an isolated
environment and run with two Rayon threads on the original MP3
(`674df668c25608ef3e9199bf3b48d760642456d679729c9661ac5cb2a22e179c`),
without supplying event times, frequency bands, flight IDs or location. It
proposed 47 events in one run (32.35 CPU seconds, 99.76 seconds elapsed under
shared system load). This is a wheel measurement, not a verified build of the
pinned source revision.

A separate no-plot DOPPLERGEIST intake and discovery replay of that MP3 used
31.81 CPU seconds (including its FFmpeg child) and 171.99 seconds elapsed; its
17 event records exactly matched the saved upload discovery. The Python timing
excludes initial imports, whereas the wheel timing includes CLI startup. These
were run under changing load, with different default frequency ranges and
outputs, so elapsed times are not a reliable performance comparison. On a
second run the Python process's Linux `VmHWM` was 149 MiB, excluding FFmpeg;
the wheel process reached at least 226 MiB in 50 ms samples. Both detectors'
second-run event JSON matched their respective first outputs. The Python
`getrusage` peak-RSS figure was already elevated at process startup and is not
usable as a memory comparison.

After detection, proposals were checked against the three pre-existing
reference windows and bands. Dopplerprint had at least one time-and-frequency
overlap in each; DOPPLERGEIST's saved blind discovery also had an overlap in
each. These broad overlaps do not prove flight identity, event accuracy or
independent recall; Dopplerprint's 47 proposals and DOPPLERGEIST's 17 ridges
in 15 groups are not interchangeable hypotheses. The outputs and timing
receipt are local under
`/home/cinna/.local/state/dopplergeist-dopplerprint-review-20261103/`.

Before adopting either frontend, evaluate their blind proposals against the
same independently reviewed recordings, including negatives and fragmented
ridges; compare CPU, memory, precision and recall with matched input and output
work. A speed comparison of the full-day geolocation searches also needs the
same time window, geographic coverage, candidate accounting and scoring model.
