# Duration-eligible Risoux controls for PR 343

All 24 declared arms completed: twelve whole recordings through ordinary
discovery and the same twelve through the experimental coherent adapter. There
were no errors, timeouts, retries or replacements. Both methods reported zero
event/harmonic groups on all twelve recordings. The clip-level union was also
0/12. Each predeclared silence, biophony, wind and rain stratum was 0/3.

These are measured proposal counts on a fixed, duration-eligible cohort. They
do not establish aircraft absence, a population false-positive rate, improved
recall or location accuracy. The reference's speed/distance restrictions still
apply. The result does not justify default activation or full closure of #341.

## Selection and execution

The source is the [Risoux forest dataset](https://doi.org/10.5281/zenodo.10701274)
by Sylvain Haupert, Elie Grinfeder, Jérôme Sueur, Frédéric Sèbe, Manon Ducrettet,
Julien Barlet and Marie-Pierre Reynet. The publisher labels the selected clips
`plane=0`; that annotation is not a guarantee of exhaustive aircraft absence.

[Part A](https://github.com/1337isnot1337/DOPPLERGEIST/issues/341#issuecomment-6622899923)
fixed three clips per pure silence/biophony/wind/rain stratum, excluding all 140
previously selected Risoux members. Selection used a fixed salted filename hash,
without detector outputs. Each unchanged original ZIP member passed full CRC32,
size and SHA256 checks. The complete source-to-opaque-name mapping is in
[acquisition.json](acquisition.json). Its `audio_decoded=false` and
`detector_run=false` fields describe that earlier acquisition stage.

[Part B](https://github.com/1337isnot1337/DOPPLERGEIST/issues/341#issuecomment-6623019872)
publicly froze the [protocol](protocol-part-b.md) and
[driver](run_negative_controls.py) before execution. The application source was
`cff7d1646932cb9c99fd5fd3c18e2c36d869ad41`; the reference source was
`ed84e0f066d60833f7e9683c286a1f4838e28639`. Later PR documentation changes did
not change this run. Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0, Numba 0.68.1,
llvmlite 0.50.0/LLVM 22.1.0 and FFmpeg 6.1.1-3ubuntu5 were pinned. The optional
Numba packages were isolated from the shared environment.

Both methods received opaque paths to complete original WAVs. Labels, original
filenames, timestamps, locations and flight identities were not supplied as
detector controls. Headers remained unchanged. There were no cuts, padding,
repetition, concatenation or external normalization. The declared single-CPU
resource controls and scientific defaults were unchanged. The caps were 120 s
per ordinary arm, 300 s per coherent arm and 5,400 s for the batch, with bounded
termination cleanup. No cap was reached. Error handling was source-reviewed;
this completed batch did not exercise error or timeout paths.

The twelve native headers each describe 2,645,760 stereo frames at 44,100 Hz,
or 59.99455782312925 s. Every actual ordinary decode produced 239,979 mono
samples at 4,000 Hz (59.99475 s), with 116 observed spectral frames and a 57.5 s
frame-center span. Every actual coherent decode produced 239,978 samples at
4,000 Hz (59.9945 s), with 236 observed spectral frames. The pinned reference
uses a duration-limited load. The one-sample difference is observed; no separate
causal test of that difference was performed.

All twelve coherent inputs therefore had capacity for the unchanged 40-point
gate. This addresses the structural failure of the earlier ten-second controls;
available frames do not imply that a long, usable ridge exists. The original
24 AeroSonic rows and the separate four TUT scene controls remain unchanged.

## All twelve outcomes

Every ordinary and coherent arm below completed and was duration-eligible.
Counts describe reported groups and intermediate detector outputs, not
independent physical sources. [outcomes.json](outcomes.json) retains all 24 arm
states, decoder counts, frame counts, settings and resource measurements.

| Opaque case | Stratum | Ordinary groups | Coherent groups | Coherent raw traces | Returned fits | Reference-refined traces |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 74925ef6c3b4f695f88c | silence | 0 | 0 | 4 | 2 | 0 |
| 1bbaf638c25c317d8d45 | silence | 0 | 0 | 8 | 5 | 1 |
| c7cd61c921b0eade38e3 | silence | 0 | 0 | 5 | 2 | 0 |
| 01d9470c825c7d5faf40 | biophony | 0 | 0 | 6 | 4 | 0 |
| cc87217a241e5c50fded | biophony | 0 | 0 | 3 | 3 | 0 |
| 7740c3071e69de10ade5 | biophony | 0 | 0 | 4 | 3 | 0 |
| 519448ec9038a5d3644e | wind | 0 | 0 | 6 | 4 | 1 |
| ce7896cfb46f47ce25f2 | wind | 0 | 0 | 2 | 1 | 0 |
| 5620954e95fedd0918be | wind | 0 | 0 | 6 | 3 | 0 |
| 27b3c02225e42592a505 | rain | 0 | 0 | 7 | 7 | 1 |
| c7d28acf53f73064d96e | rain | 0 | 0 | 4 | 2 | 0 |
| e047f38ef04a4994ff0c | rain | 0 | 0 | 7 | 3 | 0 |

The [compressed actual observation journal](observations.jsonl.gz) preserves
ordinary measured paths and acceptance decisions, coherent candidates and
measured traces, fit results/inlier masks, reference-filter outcomes,
adapter-quality decisions and complete final event arrays. Each JSONL record
identifies its case and method. Added `saved_*` records copy the corresponding
completed output files; other observations retain their original values.
Nonfinite diagnostic floats have an explicit `nonfinite_float` marker rather
than becoming zero. Read the archive with `gzip -cd observations.jsonl.gz` or
Python's `gzip.open`; no audio decoder is needed.

Ordinary discovery examined 585 measured paths containing 1,877 path points;
none passed its existing acceptance rules. Coherent discovery returned 164
matched-filter candidates, 62 nonempty measured traces containing 1,747 points,
and 39 fits. All 39 fit calls returned a result. Twenty-three traces did not
reach fitting, and 36 fits were not accepted by reference refinement. Rejection
flags included 13 speed-domain, 34 slant-domain, 21 CPA-shift and 21 fit-residual
flags. These flags overlap and must not be added as independent rejection counts.

Three traces passed reference refinement and reached the unchanged adapter
quality gate:

| Opaque case / proposal | Inlier points | RMS / main frequency | Adapter rejection |
| --- | ---: | ---: | --- |
| 1bbaf638c25c317d8d45 / 2 | 38 | 0.977507% | Fewer than 40 inliers |
| 519448ec9038a5d3644e / 4 | 26 | 2.521697% | Fewer than 40 inliers; residual above 1% |
| 27b3c02225e42592a505 / 6 | 23 | 1.800471% | Fewer than 40 inliers; residual above 1% |

No threshold was adjusted after these outcomes. All final event arrays are
empty because no trace passed the declared method's acceptance rules, not
because failed measurements were converted to zeros.

## Resource measurements and reproduction

The sequential batch took 108.42 s of wall time. Ordinary arm wall times were
0.917–1.170 s (12.81 s total); coherent arm times were 6.837–14.471 s (95.29 s
total). The first coherent arm included first-use JIT compilation. Measured
process-plus-waited-child CPU totals were 11.32 s and 91.45 s respectively.
Instrumentation and serialization are included. No speedup comparison is made
against the earlier cohorts or another runtime.

Ordinary process RSS high-water marks were 163.18–165.30 MiB; waited-child
marks were 153.38–155.48 MiB. Coherent process and waited-child marks each ranged
from 270.23–321.72 MiB. These are separate process statistics; they cannot be
added into an aggregate memory peak.

The archived driver is the exact executed file, including the original workspace
paths and acquisition-manifest identity. Those paths in the driver and outcomes
are documentary, not repository-relative input locations. To repeat elsewhere,
stage the same original members and pinned sources/runtime, then adapt a copy's
paths and corresponding manifest identity while keeping the scientific settings
fixed. Preserve the archived files and use a new output directory. The executed
command was:

```sh
/workspace/scratch/e20de6666de2/.venv/bin/python \
  /workspace/scratch/e20de6666de2/risoux-negative-control-343/run_negative_controls.py \
  --manifest /workspace/scratch/e20de6666de2/risoux-negative-control-343/acquisition.json \
  --output /workspace/scratch/e20de6666de2/risoux-negative-control-343/execution-v1
```

No raw or decoded audio, runtime dependencies, caches, or deterministic template
grids are included here. Source attribution and exact member identities remain
in the linked dataset and manifest. No flight matching or localization was run.
