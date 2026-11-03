# Unchanged independent producer/scorer controls

The independent physical verifier published the retention protocol at `7fed364`
and real-geometry assessment protocol at `faef3b4` before this producer/scorer
integration was ready. Both files were extracted unchanged from those commits
and executed against W2 source `4cd0ba3` (production checkpoint `c69ac12`).
**All eight checks passed**, zero failures/skips, 10.04 s.

These use actual Track propagation, robust source fits and association scores,
without a fake scorer or injected assessment/success metadata. The controls cover
supported/unsupported/rejected clock trials, a finite winner alongside unknown
trials, every tile/fine retention drop, exact seed identities, partition/resume
invariance, and event/work caps remaining incomplete.

[receipt.json](receipt.json) records the exact command and protocol/artifact
hashes. The native output inventory preserves hashes for every generated report,
ledger, checkpoint and fixture; the original data/index caches remain local under
the stated ignored output directory. These regional synthetic controls establish
physical/accounting behavior, not national recall or real localization accuracy.
