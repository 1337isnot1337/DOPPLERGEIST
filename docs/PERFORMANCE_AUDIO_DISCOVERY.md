# Real audio discovery performance notes

Date: 2026-11-03. Measurements below use real recordings only. No audio or
flight data was synthesized, and no location search was run on these clips.

## Measured cost in DOPPLERGEIST

The 180-second YouTube recording `yt-yjJrC9UvIrk` produced 32 ridge records.
At the same code revision and on the same input, the original CLI rendered a
summary plot and 32 per-event spectrograms: **142.86 s** wall time and
**306,232 KiB** peak RSS. With all plots disabled it took **17.51 s** and
**148,608 KiB** and produced the same `discovery.json` bytes and ridge CSVs.
The per-event plot renders alone accounted for 85.90 s under `cProfile`.

A longer real recording provides a scale check: the 3,726.45-second Bourne
Garden recording on Wikimedia Commons ([source and CC BY-SA 4.0 attribution](https://commons.wikimedia.org/wiki/File:Bourne_Garden_2020-08-28_0843.mp3))
produced 222 ridge records in 62 chunks. At `80ca06c`, the plot-heavy scan
took 462.66 s and 398,036 KiB peak RSS. At `7a8dd27`, with CLI plots disabled,
it took 285.94 s and 158,208 KiB. The output discovery JSON is byte-identical
across all three saved runs (SHA-256
`750a54c1dda9f85f06ef556ca3241e0f5ff04ced2ed7fec7f8da153afcbaf480`). The
two revisions have identical `discovery.py` and CLI implementation before the
plot-option change. The 38% wall-time reduction is an observed sequential run,
not a hardware-isolated benchmark.

An instrumented no-plot run of the hour-long recording is useful for locating
the remaining detector work, but its timings include profiler overhead and a
low-priority process competing with the national search. In that profile,
`discover_events` took 147 s cumulative: `_paths` took 97.6 s and `_spectrum`
40.6 s. Repeated short-window slope medians were a substantial `_paths` cost.
Intake took 218 s, including 204 s inside reads from FFmpeg's output pipe;
this run does not yet separate decoder CPU from wait time under host load.

A separate sequential A/B then ran only `discover_events` over the same cached
decoded Commons audio, with plots disabled. Replacing NumPy allocation/diff/
median work for each short slope history with `statistics.median` reduced
discovery from **111.456 s** to **94.616 s** (**1.18x**), kept all 222 ridge
records, and preserved the exact JSON SHA-256 above. A smaller microbenchmark
over 2,731 real ridge windows was also numerically identical and took 0.354 s
with NumPy versus 0.058 s with the standard-library median. These are paired
measurements on a loaded host, not an isolated steady-state benchmark; the
CLI's decode-inclusive runtime was not remeasured after this change.

The plot change makes per-event PNGs opt-in while retaining all ridge
measurements in JSON and CSV. The CLI also makes its summary plot opt-in. The
library keeps its existing summary-plot default for callers that use the image
as an inspectable artifact. These changes do not reduce event recall. The
short-history median change preserves the entire recorded discovery JSON on
the hour-long real clip.

DOPPLERGEIST's application and detector control flow is Python. NumPy/SciPy
provide compiled array, FFT and peak-finding kernels; the repository has no
Rust or C extension for this path. The one-hour profile shows that Python path
linking and repeated small-array work remain candidates for a focused native
kernel, while the array transforms already call compiled libraries.

## Event count and downstream cost

In the active real national search, 15 harmonic groups led to 1,527,829 timing
trials across 680 completed tiles. That confirms that additional independent
event groups can increase association and scoring work. It does not justify
dropping detections indiscriminately: multiple correct events constrain the
shared recording clock and reject wrong hypotheses. Harmonics and fragments
must be consolidated before counting independent events; uncertain groups need
to be screened with measured evidence and recall checks.

## Relevant open implementations

- [doppler-locate](https://github.com/digitalis-p/doppler-locate) keeps its
  workflow in Python and uses NumPy/SciPy, Numba, and optional OpenMP/CUDA
  kernels. Its automatic detector uses a bank of 108 constant-speed flyby
  shapes, FFT cross-correlation on a whitened log-frequency spectrogram,
  steady-tone suppression, harmonic grouping, then ridge tracing. Its README
  reports about 70 seconds for one hour on 32 CPU cores. The method is a
  candidate for a coarse acoustic sieve before the current tracker; adopting
  it needs real-recording recall comparisons before it can reject paths. Its
  separate geometric search uses compiled track-local CPA/candidate loops and
  reports 126 s / 20 GB on CPU versus 80 s / 12 GB on an RTX 4090 for its
  CONUS case. The kernel's float32/parabolic CPA is a proposal technique;
  DOPPLERGEIST's continuous-track scorer must still decide final candidates.
- [dopplerprint](https://github.com/Hexay/dopplerprint) uses a Rust core with
  Python orchestration. On its real one-hour recording, caching repeated
  fragment-pair curve fits cut discovery CPU from 249 s to 11.5 s with
  byte-identical JSON. Its real search scorer fell from 443 to 117 CPU-seconds
  after hoisting log-frequency terms and using binary search for monotone f0
  sweeps. DOPPLERGEIST already uses local-slope fragment stitching rather than
  those repeated curve fits, and its primary ranking uses physical ridge
  residuals rather than the same brightness score, so these exact changes do
  not transfer directly.
- [Hermes aircraft Doppler geolocation](https://github.com/mojomast/hermes-aircraft-doppler-geolocation)
  uses Python/SciPy Viterbi ridge tracing with a manually selected band and
  time interval. It is a compact reference for ridge fitting and an explicit
  false-fit gate, but it does not provide a whole-recording automatic scan or
  a measured optimization.
- [EchoTrace](https://github.com/Goprogabriel/echotrace) is a browser-local
  TypeScript implementation that runs analysis in Web Workers. It bounds
  spectrogram storage at four million cells by increasing the frame hop for
  long clips, and its ridge dynamic program uses a linear-time L1 distance
  transform instead of a pairwise transition search. Those are useful
  algorithmic ideas, though DOPPLERGEIST already streams 120-second chunks and
  its tracker has different association semantics. EchoTrace caps proposals at
  eight and has users select up to three; copying that cap would trade away
  recall. Its own documentation says there is no independent real-world
  validation. The synthetic demo was not run or used as evidence.

## Next measurements worth doing

1. Time FFmpeg intake separately from scanning, on an otherwise idle host, so
   wall time is not mistaken for Python detector cost.
2. Compare a real-recording template-bank pre-screen against current discovery,
   measuring recall and false proposals before feeding it into association.
3. If `_paths` remains the dominant detector cost after that comparison, compile
   only its path-linking loop and keep orchestration in Python. The present
   evidence does not support a blanket language rewrite.
