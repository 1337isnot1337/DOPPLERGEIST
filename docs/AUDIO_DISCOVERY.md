# Automatic acoustic episode discovery

Discovery scans the whole recording without event windows, aircraft IDs, flight
observations, coordinates or a flight-geometry template. Its unit is a **canonical
acoustic episode**, containing measured tonal child tracks. Common frequency
motion does not establish a single physical source, physical source motion, or
aircraft identity. Simultaneous trajectories can remain separate, and physical
source multiplicity is explicitly unresolved, including within an episode.

The Python API still returns `list[DetectedEvent]`: one record per measured child
track, with the canonical episode ID in `harmonic_group_id`. Count distinct group
IDs to count proposals. `discovery.json` is now **schema_version 2** and is the
explicit episode catalog. The shared upload/result and DetectedEvent contracts
remain version 1. See [interfaces](INTERFACES.md#detected-events).

## Processing and acceptance

1. Decode to a mono, disk-backed f32 cache. The automatic adapter selects 4, 8,
   16 or 32 kHz according to requested global frequency coverage. FFmpeg applies
   channel averaging and explicit swresample low-pass filtering (filter_size 64,
   cutoff 0.95). Sample zero remains the first decoded sample after codec skips;
   resampling can round the final length by a sample. UTC requires separate
   recording-clock evidence.
2. Scan overlapping chunks (120/60 seconds by default). The default spectrum is
   a 2-second Hann window, 0.5-second hop, 40–1600 Hz. Temporal whitening and
   frequency-wise robust contrast retain the existing measured-peak method.
   Peaks carry frequency, contrast, and measured spectral amplitude in dB.
3. Retain provisional paths of at least four observations **before** duration or
   motion rejection. Reconcile duplicate measurements across chunks and then
   reciprocal-unique continuations. Distinct peaks in the same chunk are not
   deleted as near-unison duplicates. A continuation requires compatible endpoint
   slopes in either direction, forward and backward prediction, uncertainty,
   observed support and a gap penalty. A turn hidden in a gap is unresolved.
4. Assess resolved excursion, distributed motion, local prediction residual,
   sustained turns, and total variation. Differences and slopes use timestamps
   in seconds; missing intervals do not count as observed motion. Rising,
   falling and one sustained turning trajectory are eligible. Stationary tones,
   isolated tone switches, repeated modulation and wandering fail explicit gates.
5. Fit constant frequency scales between components with substantial shared
   support, resolved motion, high curve correlation and uncertainty-aware
   residuals. A bounded integer-family model (orders 1–12, smallest total order)
   supplies secondary harmonic evidence, including missing fundamentals.
   Noninteger relationships require correlated measured amplitude envelopes.
   A ratio match or temporal overlap alone is insufficient.
6. Reconsider groups jointly. For three or more components each needs two strong
   motion witnesses; every supported pair must agree with one joint scale fit,
   including short overlaps that cannot establish motion independently. A weak
   bridge cannot transitively collect unrelated groups. Sorting observations and
   associations makes grouping invariant to input order. Unresolved strong links
   are counted and traced separately; separate proposals do not certify separate
   physical sources. The model has one scale per child, at most 32 children per
   episode, and no free time warps or high-order rational search.
7. Apply episode acceptance using the union of **observed hop-sized cells**, not
   interval span or spectrogram-window footprints. Sustained acceptance needs
   at least 12 observed seconds and 65% support. Brief acceptance needs at least
   3 observed seconds, 85% support, and a child with median contrast >=4.5,
   excursion >=6 frequency-uncertainty units, distributed motion >=60%, and
   prediction-error q95 <=0.75. These are uncalibrated engineering criteria,
   not a blanket reduction of the duration/contrast thresholds.

Gaps are never filled with invented ridge observations. Stitch gaps are at most
20 seconds and at most 35% of the pair's observed support; aggregate acceptance
also penalizes missing support. The output distinguishes the observed cells
from the wider spectral-window timing uncertainty. Very brief accepted episodes
with fewer than ten total samples are acoustic-review evidence only;
`quality.matching_eligible=0` prevents the matching adapter from failing on them.
The application returns `brief_acoustic_evidence_only` if none are matchable.
Other proposals need not match any flight.

## Coverage and resources

The default coverage remains 40–1600 Hz for compatibility. Higher frequencies
require decoding the original source at a sufficient rate; changing a scanner
setting cannot restore frequencies discarded in an old cache. The automatic
adapter and scanner CLI choose the rate before intake. Direct Python callers
must use `required_sample_rate(settings)` when invoking `intake_recording`.
Requested upper coverage must be <=45% of both source and decoded rates. A
request outside this usable range fails with `unsupported_frequency_coverage`;
it is not reported as an exhaustive negative. The lower limit requires at least
two cycles per window. Longer windows improve low-frequency resolution; shorter
windows improve temporal resolution while increasing frequency uncertainty.

The `coverage` object records requested and analyzed bin ranges, eligible peak
centers, source/decoded rates, resolution, hop, window, transition guard and edge
policy. Outermost bins support interpolation and cannot be peak centers. Inputs
shorter than a complete window have no spectral observations. The high-rate path
uses a single spectrum per chunk, so there are no overlapping frequency bands
that could duplicate proposals. Chunk grids must align to whole sample hops;
chunk provenance is retained through deduplication and stitching.

Default explicit limits: 60 peaks/frame, 4,096 provisional paths, 500,000 retained
observations, 200,000 association work units, 8,000,000 full-spectrum cells per
chunk and 100 diagnostic trace entries. Association work includes repeated joint
fit checks, not only unique pairs. Joint fit matrices have at most 32 columns.
Exceeding a processing budget raises a typed failure and records the limit;
it does not silently drop candidates and claim a complete scan. There is no cap
of two, three or four canonical proposals per recording. Increasing a work limit
in the Python settings is an explicit resource choice.

The decoded cache uses `4 * rate * seconds` bytes: about 55 MiB/hour at 4 kHz,
220 MiB/hour at 16 kHz. Working spectra stay chunk-bounded; raising rate increases
FFT memory and CPU, and reducing the hop increases frame count. Spectrum cells
are checked before allocation. The [engineering report](ACOUSTIC_EPISODES_REPORT.md)
records measured RSS, time and output volume, including regressions.

## Outputs and compatibility

`discovery.json` contains:

| Field | Meaning |
| --- | --- |
| `status`, `failure` | `complete` with zero proposals is a valid in-band result; `failed` is an execution, coverage or budget failure |
| `source_sha256`, `code`, `settings`, `runtime_s`, `coverage` | Input identity, git/implementation identity, library versions, effective configuration and runtime |
| `events` | Compatible measured DetectedEvent children; ridge points are stored once here |
| `episodes` | Canonical IDs, child IDs, raw track/chunk membership, fitted frequency scales, integer orders, observed intervals/gaps, confidence category and limitations |
| `counts` | Separate raw per-chunk paths/observations, provisional/deduplicated/stitched candidates, accepted children and canonical proposals |
| `ridge_count` | Accepted measured child count, retained for older count consumers |
| `rejections` | Counts and measured/threshold ranges per rejection reason; optional bounded candidate traces |
| `reconciliation_counts`, `reconciliation_decisions` | Counted and bounded duplicate, stitch, joint-group and unresolved-relation decisions; truncation is explicit |

IDs hash source identity and ordered measured content, and do not depend on input
ordering, proposal enumeration or unrelated accepted proposals. They are stable
for the same measurements and effective configuration, not guaranteed invariant
to codecs, alternate chunk whitening, or resampling that changes measurements.
Each child retains original raw-track identifiers and amplitude measurements;
observed frequency scales replace the old ratio dictionary in the matching
adapter. Legacy event groups without these scales still use their old adapter.
Equal aggregate weight per child preserves the existing consumer convention;
additional components do not become additional independent time constraints.

Confidence is categorical and uncalibrated: `uncalibrated_supported` or
`uncalibrated_brief_limited`. Frequency uncertainty uses the spectral resolution
and robust deviation, not a calibrated interval. `frequency_sigma_hz` and
`frequency_uncertainty_hz` retain the same diagnostic; matching retains its
>=1 Hz loss-scale floor. Every episode says `physical_motion_confirmed=false`
and `physical_source_multiplicity=unresolved`.

Schema 2 removes the duplicate `harmonic_ridges` array, legacy `fragment_links`
and automatic per-child CSV files. Read measurements from `events` and decisions
from the reconciliation fields. The plot benchmark reads both artifact versions.
Old evidence is preserved; [the starting-version documentation](https://github.com/1337isnot1337/DOPPLERGEIST/blob/451b67f01dcd1dfe44d47c42407f404706a5a9b7/docs/AUDIO_DISCOVERY.md)
contains historical counts and methodology, including cancelled synthetic work.

## Commands

```bash
# Default acoustic-only scan. A fresh output directory is required.
PYTHONPATH=src .venv/bin/python scripts/discover_audio.py input.mp3 \
  --output results/discovery --plot-summary

# Global wider coverage; source must actually retain those frequencies.
PYTHONPATH=src .venv/bin/python scripts/discover_audio.py input.wav \
  --min-frequency-hz 20 --max-frequency-hz 6000 \
  --output results/discovery-wide --plot-summary

# Optional higher temporal resolution and bounded rejected-candidate traces.
PYTHONPATH=src .venv/bin/python scripts/discover_audio.py input.wav \
  --window-s .5 --hop-s .125 --max-frequency-hz 6000 \
  --output results/discovery-fast --detailed-candidates --plot-event-details

# Software properties and existing genuine recorded evidence; no audio synthesis.
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_episodes.py \
  tests/test_real_discovery_normalization.py tests/test_real_upload_verification.py \
  tests/test_contracts.py tests/test_job_resume.py
```

Summary plots use canonical episodes. Optional detail plots render one bounded
spectrogram per episode, with all its child tracks, once. They do not render the
same group repeatedly for each harmonic. Normal operation records aggregated
noise rejection rather than writing a file per rejected fragment. Input/decoder
failures exit unsuccessfully; discovery failures additionally write a failed
artifact. No command above acquires flight data or estimates a location.
