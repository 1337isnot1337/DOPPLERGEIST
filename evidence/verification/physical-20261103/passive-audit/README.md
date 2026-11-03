# Passive completed-run audit

This read-only auditor checks stored source hashes, audio bytes, configuration identity, all tile hashes and work counts, public/internal candidate consistency, shared clocks, original event mapping and per-event score contributions. It does not run any scientific producer, read evaluation labels, change a decision or establish location accuracy.

The preserved first execution audits the already completed two-event run `bb3e96c615d44abaa75bcf75db2cbeb3` against published source `98b14955741f32cf6fb7592bbf44df050a5bd309`. Every integrity check passed, including all 19,278 tile records. Its decision remains `inconclusive/ambiguous_locations`; this audit does not convert a close candidate into acceptance or fix the known historical full-profile ordering issue.

The same auditor is prepared for the upload verifier's canonical four-event result. That job has not been audited by this worker yet. Pass its actual terminal job directory, source revision and canonical audio digest, with `--expected-groups 4`, then write to a new output path. Keep all observations, including failed integrity checks. A separate post-run truth join is required for distance thresholds and physical accuracy.
