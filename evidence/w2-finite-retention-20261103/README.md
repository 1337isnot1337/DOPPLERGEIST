# Finite-retention verification

Frozen source: `9f60816`, including current main `8cdb7ae`. The full command and
native JUnit/log are preserved in [receipt.json](receipt.json): **228 tests and
6 subtests passed**, zero failures/skips, 75.82 s. The scorer classified-trial
adapter remains an explicit integration dependency; absent metadata cannot yield
assessed mode IDs or complete finite evidence.

The [retention fixture](../../scripts/benchmark_finite_retention.py) generates
invented four-group scored seeds, includes exact duplicates, applies both per-stage
and global top-100 retention, and audits every original distinct seed on disk. Its
monotonic analytic unpruned reference gives the exact retained identities and
maximum discarded score without allocating a national reference list.

| Distinct seeds | Stages of each kind | Elapsed | Process VmHWM | Ledger bytes |
| --- | --- | --- | --- | --- |
| 16,384 | 16 | 1.60 s | 210.22 MiB | 10,678,272 |
| 131,072 | 128 | 12.39 s | 210.25 MiB | 85,999,616 |

Both runs passed every analytic count, identity, duplicate and bound check. The
stage buffer is fixed at 1,024 seeds. Linux `/proc/self/status` supplies each new
process's live memory/high-water measurements; the reports also retain baseline
RSS. These two finite measurements support bounded stage-memory behavior, not a
proof of asymptotic resource use. SQLite storage grows with evaluated modes.
Large ledgers remain in ignored, separately named `results/` directories; only
the small JSON reports and digests are committed.

No audio, flight data, recorder truth or localization search is used in this
fixture. It does not demonstrate event discovery, national search recall,
continuous-space uniqueness, a calibrated interval or real geolocation accuracy.
The finite producer and compatibility mapping are described in
[FINITE_SEARCH_PRODUCER.md](../../docs/FINITE_SEARCH_PRODUCER.md).
