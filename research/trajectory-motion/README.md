# Motion-inconsistent historical trajectory audit

This is the primary's targeted reproduction/fresh-raw leg of issue64. It leaves
production interpolation, scores and coverage unchanged. It does not close that
correctness gate or establish localization accuracy.

The canonical Parquet and both raw archive parts match their released SHA256
values. The exact v2 SQLite index matches the published scale-run digest and
input hash. All329 native timestamps pair across the four selected aircraft.
Selection came from prior failed national tiles; it is not a prevalence sample.

| Aircraft | Exact stored maximum, m/s | Fresh nullable-source maximum, m/s | Finding in the declared window |
| --- | ---: | ---: | --- |
| a6cc10 | 1011.27 | 847.88 | Native chord already674.18m/s;3 unsupported intervals remain |
| ae8b78 | 416.87 | 244.92 | No interval exceeds343m/s after nullable derivative inference |
| ae05a8 | 451.95 | 288.85 | No interval exceeds343m/s after fresh normalization |
| c01125 | 52043.51 | 35699.29 | Native chord already34702.29m/s;19 unsupported intervals remain |

These are modeled speeds from inconsistent inputs, not measured actual aircraft
speeds. The declared343m/s threshold is the current globally subsonic assumption.
It does not imply every observer has a nonunique retarded-time solution.

The earlier1001-point whole-track audit reported ~14600m/s for c01125. The new
per-interval stationary-point enumeration finds a much narrower peak: the native
observations move14574.956m in0.41999984s. An independent65-point sample INSIDE
that short interval reproduces the52043.51m/s stored-Hermite maximum. Fresh
normalization reduces it but leaves an impossible-under-model position/time
sequence. A6cc10 similarly moves5905.843m in8.76s. Bad positions, clock errors or
identifier collisions remain possible causes; this audit does not decide which.
Full-trace derivative support gives the same worst in-window peaks.

## Two normalization causes established

Historical missing headings were used as heading zero in the legacy normalizer.
That fabricates nonzero northward velocity as well as zero eastward velocity.
For ae8b78,98 historical northward components are finite although fresh source
heading is missing; ae05a8 has97 such components. This is more than losing a
missing-value marker on numerical zero. Fresh position-derived velocity fixes
these two tested subsonic failures while preserving source missingness.

A separate same-normalizer ablation explains ae05a8's137.16m height difference.
The historical ingestion clips raw observations BEFORE normalization; its
15-minute slice contains no usable geometric-minus-baro reference. It therefore
stays labelled barometric. Normalizing the full trace first retains references
outside that window, producing ellipsoidal_interpolated heights137.16m higher.
Applying the SAME current normalizer in the two orders reproduces that exact
change. This demonstrates an input-support/order effect, not independently
verified GNSS altitude. Preserve the distinction and its uncertainty.

## Verification and reproduction

[PROTOCOL.md](PROTOCOL.md) records the initial selection and the later explicit
height-order ablation. The independent speed controls include constant velocity,
zero endpoint derivatives, a noncollinear closed form and30 random curves checked
against separate SciPy spline evaluation. A gap/zero-retention control preserves
segmentation; a height-support control reproduces the order effect.

- Frozen source9f5bd54:207 tests plus6 subtests pass, no failures/skips,41.57s.
- Follow-up sourcea422148:208 tests plus6 subtests pass, no failures/skips,42.08s.
- Both use clean Python3.14 and emit one existing pandas fallback-dtype warning.

Each [frozen](frozen/verification.json) and [follow-up](order-ablation/verification.json)
receipt records exact source/tree/script/input/report hashes and native JUnit.
Every interval and every target outcome is retained, including zero audit failures.
The full raw4-aircraft traces remain reproducible from checksummed archive members;
small canonical/fresh window snapshots are included. No audio or source video is
used. A compact cross-case [summary](summary.json) is supplied.

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_trajectory_motion.py \
  --canonical /restored/conus-alltypes-faint-window.parquet \
  --index /frozen/conus-alltypes.sqlite \
  --parts /restored/v2026.09.08-planes-readsb-staging-0.tar.aa \
          /restored/v2026.09.08-planes-readsb-staging-0.tar.ab \
  --ids a6cc10 ae8b78 ae05a8 c01125 \
  --window 1788899400 1788900300 --output /new/audit-output
```

## Production handling requirements remain open

Rebuild from nullable raw motion fields with documented normalization support;
legacy zero/nonzero fabricated derivatives cannot be repaired by reindexing.
Independently quarantine or split persistent unsupported observation sequences,
recording original intervals/reasons and missing scope. One bad track must not
erase clean candidate diagnostics for an entire tile. Excluded data cannot turn
partial scope into complete coverage. Add clean/invalid/mixed-track regression
controls and retain the real failed scale outcome. W2 owns input/index semantics;
W3 owns physical-scoring behavior. No interpolator was selected using location
truth, and no new worker was deployed for this audit.
