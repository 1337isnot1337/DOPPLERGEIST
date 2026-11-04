# Trajectory motion support

The emission-time model assumes subsonic three-dimensional source motion. A
positive observer-specific arrival derivative does not establish this assumption:
an inconsistent native position interval can pass that radial check and fit an
acoustic ridge exactly from a side observer. No interpolation or acoustic fit
repairs such a source inconsistency.

`Track.validate_motion_support(c)` checks each native Hermite interval before CPA
proposal generation. A quadratic Bezier velocity bound cheaply certifies ordinary
intervals. When that bound reaches sound speed, endpoints and real stationary
points of squared speed determine the continuous maximum. Results are cached per
interval and rechecked against each requested sound speed. This uses floating
point polynomial roots, not formally certified interval arithmetic; a relative
1e-10 margin treats the sonic boundary as unsupported. Work and storage scale
linearly with the number of native intervals, with at most one cubic root solve
per suspicious interval over the Track's lifetime.

Both sparse and dense `search.cpa_table` paths, and `Track.closest_approaches`,
invoke the whole-source validator. An unsupported interval raises
`AcousticSupportError(track_id, "non_subsonic_motion")`. Its additive
`emission_intervals_s` field retains the affected native time intervals. CPA has
no narrower receive envelope: `receive_intervals_s` is `None`. The outer search
may preserve other track rows while recording the whole affected track/tile
scope as lost model coverage. It must keep the search partial and finite evidence
incomplete. Calling the CPA function directly still propagates the typed failure;
it does not silently drop the source.

The tiled search can make a narrower spatial proof after its existing whole-track
clock exclusions. Every unsupported native interval's cubic Bezier position box
must lie strictly outside the receiver box by more than the search radius. In
addition, both endpoints of every original CPA sampling edge that touches an
unsupported interval must lie strictly outside the original KD query radius,
`search_radius + 2 * global_max_sample_step`. Such an edge cannot enter the
sampled-minimum or endpoint-refinement path. This second condition rejects a
native interval whose own curve is distant but whose crossing sample edge is
not proved irrelevant.

The proof uses the original Track, spline, timestamps, sampling lattice, global
maximum sample step and flight ID. It does not split the trajectory or create
new segment endpoints. The receiver box encloses the actual stage receivers;
proof reuse is limited to that box, the same sound speed and sampling step, and
no larger radius. A one-micrometre plus scale-dependent floating-point margin is
subtracted from distance lower bounds, followed by outward rounding. Time-edge
overlap includes the existing solver-scale timestamp tolerance. Equality,
nonfinite bounds, modified motion methods or any failed proof retain the original
whole-track unsupported result. These are conservative floating-point checks,
not formally certified interval arithmetic.

Only this bounded tiled CPA path opts into the proof. Direct public CPA calls
retain whole-source validation. A successful spatial proof records the excluded
native intervals and bounding inequalities as `interval_supported_cpa_tracks`;
it supplies no acoustic-arrival exemption. The direct acoustic check below still
uses every original unsupported interval.

Direct `Track.acoustic` scoring checks only possible arrivals from unsupported
native intervals. Cubic Bezier position boxes bound minimum/maximum range to the
observer; adding those travel-time bounds to the native interval encloses all
possible arrival times without assuming monotonic motion there. An overlapping
requested receive sample raises the same typed failure with both emission and
conservative receive intervals. A separate, clean event outside these envelopes
can retain its original emission-time solution even if the trace is inconsistent
elsewhere. An entire native interval is conservatively unsupported, including
its slower portions; this guard does not split or repair it. Existing
`non_monotone_arrival` failures and messages are preserved.

The finite Newton iteration must also finish with an emission-time correction
within 1e-7 s or four receive-timestamp ULPs, whichever is larger. A finite last
iterate is insufficient: a subsonic straight near-sonic control previously
returned emission times about 293 s from the analytic solution after ten
iterations. An unfinished solve now raises `emission_solver_not_converged` and
remains unknown. Samples outside the declared trajectory support retain NaNs;
they do not require an extrapolated converged root.

The robust clock-trial adapter records these failures as unknown, never as an
acoustic rejection or an evaluated fit. A perfect ridge match cannot establish
physical support. The guard does not change source observations, velocity
inference, interpolation, altitude labels, gap rules, clock grids or acceptance
thresholds. It does not establish source correctness, independent real accuracy
or complete national coverage. The fresh-raw audit and preserved historical
failures remain in [research/trajectory-motion](../research/trajectory-motion/README.md).

Independent controls cover a 750 m/s interior peak hidden by zero measured knot
velocities and monotone side-view arrival times, its incorrectly perfect old
acoustic fit, a 300 m/s control, an unaffected separate event, actual sparse/dense
CPA failures, sound-speed sensitivity, conservative arrival envelopes and a dense
continuous-speed oracle. W2's outer isolation must additionally verify an actual
bad-source plus clean-source search and all-invalid abstention.

## Real interval-exclusion checks

`tests/test_real_motion_interval_cpa.py` uses the unchanged released reference
archive and the measured ridge workload in `tests/data/real-search-workloads.json`.
Set `DOPPLERGEIST_REAL_REFERENCE_ROOT` to its restored checkout and
`DOPPLERGEIST_REAL_FLIGHT_INDEX` to the matching existing regional index, then run
that test file. These are development receiver hypotheses, not microphone ground
truth or complete aircraft coverage.

At the two recorded hypotheses, the proof admits 26 and 15 track/receiver pairs;
36 and 11 remain unsupported. The resulting 27 and 20 CPA rows exactly match the
unchanged sparse proposer with only the whole-track validator bypassed for this
diagnostic comparison. That bypass supplies no physical support; the spatial
inequalities supply the narrower CPA support. The measured-ridge offset workload
keeps the same 28 ranked candidates, scores and 7,623 unknown clock trials while
recovering two CPA rows from one previously excluded track. Separate checks retain
two actual first-interval passages and a final-interval passage on unchanged
tracks. Acoustic arrivals from invalid native intervals remain unknown, including
the arrival-envelope endpoints. The finite ledgers
retain the same 28 scored modes and 168 unknown-score bound envelopes, with
identical validated stage checksums.

The recovered track contributes no retained mode or unknown-score envelope within
that original limited clock window. A separate component check calls
`Track.acoustic` at all 47 recovered CPA receive times and obtains finite
supported output. The same recovered track also reaches the ordinary free-clock
scorer with the unchanged measured ridges: 35 associations produce 20 finite
hypotheses, while 253 clock trials remain unknown. Rows and trial assessments
exactly match the diagnostic original CPA path. This check uses the normal clock
hypothesis generator outside the original start window; it does not establish
the recording clock, aircraft association or receiver location.

The independent two-second dense proposer returns 25 and 18 rows. Its minima
rule uses the sequence of per-edge minimum distances, which can erase a high
shared vertex between nearby passes. The four extra sparse proposals are
interior passes, not new endpoints. A 0.125-second continuous-spline reference
finds a nearby minimum for every sparse row, with maximum observed differences
of 1.20 seconds and 16.03 metres. It also finds additional narrow minima. These
comparisons do not claim equality of the existing dense and sparse proposers or
continuous-minimum completeness. The increment preserves the existing finite
proposal algorithm and its known sampling limits.
