# Targeted trajectory-motion audit protocol

Issue64 identifies four source identities: a6cc10, ae8b78, ae05a8 and c01125.
Their selection comes from the prior failed national scale tiles, independently
of any recorder position. Freeze the existing v2 index and canonical15-minute
Parquet, time1788899400 through1788900300 (2026-09-08 20:30–20:45UTC), and the
two original daily archive parts before comparison. Compute source/member/code
hashes and retain missing/failed cases. This is a targeted explanation study,
not an estimate of whole-archive defect prevalence or localization accuracy.

Enumerate endpoints and all real interior stationary points of squared cubic
Hermite speed in normalized interval time. Its derivative is at most cubic.
Verify against constant-velocity and closed-form zero-tangent/noncollinear
controls, plus independent SciPy spline samples. Floating-point polynomial
roots are not a certified mathematical enclosure. Check every observed interval
against65 samples, preserve every interval, and flag speeds >=343m/s as outside
the declared globally subsonic model assumption. This does not establish that
every observer has a nonunique acoustic solution or that the aircraft actually
flew at that speed.

Compare these unchanged inputs:

1. Canonical observations with the current gap/dedup/velocity rules.
2. Exact stored index payloads, including their payload checksums.
3. Raw traces normalized in full before applying the same15-minute window and
   segment-local velocity rules.
4. Fresh full-trace segmentation/derivative support, reporting only intervals
   whose endpoint times both lie inside the comparison window. This distinguishes
   window-edge derivative inference from persistent internal source problems.

Join native observation timestamps exactly and report unmatched samples,
position/altitude differences, missing motion fields and historical zero fills.
Report chord speed, endpoint derivatives, continuous maximum, its time and all
unsupported intervals. A chord already exceeding343m/s is a position/time
problem under the model regardless of Hermite interpolation. A subsonic chord
with an interior peak above that threshold needs separate derivative/interpolant
examination. Do not tune thresholds or select an interpolator by recorder error.

Keep production code, source data, acoustic scores and coverage decisions fixed.
Fresh normalization alone does not repair an observation jump. Hand measured
handling requirements to W2/W3; leave issue64 open until production handling and
explicit lost-coverage semantics pass verification. The audit uses no audio,
recording coordinates, flight-match truth or new worker deployment.
