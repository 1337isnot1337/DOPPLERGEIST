# PR 343: duration-eligible Risoux control supplement, part B

This protocol is fixed before any selected recording is decoded or passed to a
detector. Part A selects twelve unchanged, publisher-labelled `plane=0` originals
in issue 341 comment 6622899923. This supplement stays separate from the previous
24 AeroSonic cases. There is no tuning partition, replacement rule, threshold
search, or default activation in this twelve-file supplement.

## Source and runtime

- DOPPLERGEIST: `cff7d1646932cb9c99fd5fd3c18e2c36d869ad41`, clean detached checkout
  at `/workspace/scratch/e20de6666de2/DOPPLERGEIST-pr343-negative-runtime`.
- Reference: `digitalis-p/doppler-locate`,
  `ed84e0f066d60833f7e9683c286a1f4838e28639`, clean detached checkout at
  `/workspace/scratch/e20de6666de2/reference-doppler-locate-ed84e0f`.
- Python 3.12.14; NumPy 2.3.5; SciPy 1.17.0; Numba 0.68.1;
  llvmlite 0.50.0 with LLVM 22.1.0; FFmpeg/ffprobe 6.1.1-3ubuntu5.
- Numba and llvmlite are installed only in
  `/workspace/scratch/e20de6666de2/coherent-runtime-343/site-packages`.
  Existing Python, NumPy, SciPy and FFmpeg are used read-only. The shared
  environment is unchanged. Import-only checks passed; no audio was used.
- Numba's official support table lists Python 3.10 to below 3.16, NumPy 2.0 to
  below 2.6 and llvmlite 0.50.x for Numba 0.68.1. Installed wheel requirements
  agree. Source: <https://numba.readthedocs.io/en/stable/user/installing.html#version-support-information>.

## Inputs and execution order

Use all twelve original WAVs in part A's declared order. Acquisition must verify
each member's complete CRC32, byte count and SHA256 before it is eligible to run.
The runner checks the acquisition manifest and input hashes before launch.
Each decoder receives only an opaque audio pathname. Labels, original filenames,
station identifiers, timestamps and location metadata are not supplied as
detector controls. The unchanged WAV headers can still contain metadata.
There is no supplied recording clock, event interval, selected frequency band,
flight identity, search box, cut, padding, repetition, concatenation or external
normalization. The existing decoders process the complete original stereo WAVs.

For each case, run the ordinary method, then the coherent method, in separate
fresh child processes. Run cases sequentially. First-use JIT compilation is
included in the observed runtime. Use a new initially empty Numba cache for this
batch; later cases may reuse its compiled kernels. Do not perform a warmup on
synthetic or selected audio.

## Resource limits

Use one available CPU, selected as the lowest member of the launch process's
allowed affinity set. Child processes inherit that affinity. Set
`NUMBA_NUM_THREADS=1`, `NUMBA_THREADING_LAYER=workqueue`, `OMP_NUM_THREADS=1`,
`OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `NUMEXPR_NUM_THREADS=1`,
`VECLIB_MAXIMUM_THREADS=1`, and `PYTHONHASHSEED=0`. The coherent fitting pool has
one worker. An execution wrapper sets the reference's explicit SciPy `rfft2`
and `irfft2` calls to `workers=1`; environment variables alone cannot override
their original `workers=-1`. A local FFmpeg launcher adds only `-threads 1`,
`-filter_threads 1` and `-filter_complex_threads 1`. No scientific parameter or
source file changes for resource control.

The ordinary method has a 120-second wall limit per case. The coherent method
has a 300-second wall limit per case. These limits include startup, decoding,
computation and serialization. The entire 24-arm batch has a 5,400-second wall
limit. A supervisor stops only its own child process group on timeout and
preserves partial output. Termination has a bounded grace period: up to two
seconds after SIGTERM, then SIGKILL and up to three seconds to reap the child.
This cleanup can extend an arm's work limit by at most five seconds; the final
cleanup can likewise extend the batch limit by at most five seconds.
Errors and timeouts remain explicit unknown outcomes;
unstarted cases remain unstarted. There are no retries or replacement inputs
based on detector results. A failed measurement cannot be reported as zero
proposals.

Record wall time, process plus waited-child user/system CPU time, process RSS
high-water mark and waited-child RSS high-water mark where the OS supplies them.
RSS high-water marks are separate process statistics, not an aggregate memory
peak. Missing or interrupted measurements remain unavailable. Observation and
serialization overhead are included; do not claim a benchmark speedup.

## Unchanged ordinary method

Call `intake_recording` with its default 4,000 Hz mono decode and no time window.
Call `discover_events` with the pinned `DiscoverySettings()` defaults and save
the complete event and discovery JSON. Disable plotting only.

Defaults: chunk 120 s, overlap 60 s, 40–1,600 Hz, 2 s window, 0.5 s hop,
minimum contrast 2.5, minimum duration 12 s, minimum support 0.65,
minimum drop 4 Hz and fractional drop 0.03, maximum gap 2 s,
maximum fragment gap 20 s, maximum 60 peaks per frame. Existing duplicate,
fragment and harmonic grouping rules remain unchanged.

Observation wrappers save the measured paths before `_usable`, each returned
accept/reject decision, actual spectral frame counts, and complete final events
including every measured ridge sample. They return the original objects and
decisions unchanged.

## Unchanged coherent method

Call the pinned `scripts/discover_coherent_audio.py::capture_traces` with
`workers=1`, followed by the pinned `events_from_coherent_traces` adapter.
This uses the original full-file scan, retains the script's existing omission
of unused profile-range work, and changes no detector or quality parameter.

Reference defaults: 4,000 Hz, 1 s window, 0.25 s hop, 30–1,000 Hz,
20 s line suppression, log step 0.002, span tau 1.5, matched-filter threshold 8,
minimum contrast 0.5, chunk 1,800 s, margin 150 s, sound speed 343 m/s,
refinement enabled, maximum 400 candidates. Speed templates in m/s:
`[20, 25.9, 33.6, 43.6, 56.6, 73.4, 95.1, 123.4, 160]`.
Tau templates in seconds:
`[2.5, 3.55, 5.05, 7.19, 10.22, 14.53, 20.65, 29.36, 41.75, 59.36, 84.4, 120]`.

The reference's trace and refinement domain remain in force, including
`6 < fitted speed < 290` m/s, `35 < fitted slant < 30,000` m,
CPA movement at most `max(10, half_window/2)` seconds and
fit RMS at most `1.5 * harmonic`. The adapter requires a refined trace with
at least 40 actual inlier samples and `rms/f_main <= 0.010`; it applies no
later aircraft/close kind filter. Its pinned duplicate and supported-overlap
harmonic grouping rules remain unchanged.

Observational wrappers persist returned matched-filter candidates, grouped
proposals before/after reference refinement, every actual ridge returned by
`trace_ridge` before fitting, each fit result and inlier mask, and all refined
traces before the adapter quality filter. Preserve unsuccessful trace/fit states
and each adapter rejection reason. Save complete final event JSON and measured
samples. These wrappers observe original calls; they do not replace fitting,
candidate selection, grouping or quality decisions. Arrays below the tracer's
own brightness gate are not represented as measured traces.

## Eligibility and result interpretation

For both methods, record actual decoded sample count/rate and actual spectral
frame counts. For the coherent method, the unpadded frame count is
`max(0, 1 + floor((N - 4000)/1000))`. The expected count for these originals is
236, subject to measured decoder output. At least 40 available time frames are
a necessary condition for the adapter's 40-point rule; this is not evidence that
a valid ridge exists. Record actual trace lengths and inlier counts separately.
For ordinary discovery, record whether the observed spectral time span permits
its unchanged 12-second event rule.

Report all twelve case outcomes and all four predeclared strata. For each
method report completion/eligibility, reported event/harmonic groups, ridge count,
measured sample count, and the complete output paths. Report the number of
completed eligible clips with any proposal for each method and their clip-level
union. Do not add group counts across methods as if they were independent.
Preserve failures, partial traces and all quality-filter rejections.

The labels are the publisher's `plane=0` annotations, not a guarantee that every
clip contains no aircraft. These forest recordings address duration eligibility
and proposal burden on this fixed cohort. They do not establish a general false
positive rate, aircraft identity, location accuracy, nationwide acceptance, a
default activation decision, or full closure of issue 341. The earlier 24 rows
remain unchanged and the ineligible ten-second background rows remain labelled
ineligible.
