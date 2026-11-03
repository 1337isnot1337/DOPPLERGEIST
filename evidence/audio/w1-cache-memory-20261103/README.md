# Bounded sample-buffer residency

Production I/O fix1f95689 replaces a whole-cache memory map with seek/read of the
active float32 chunk. The file-sized resident set violated the intended intake
bound even though the decoded signal and chunk arrays were already disk-backed.
No decode, metadata, time, detection setting or association rule changes.

| Synthetic raw cache | Old RSS growth | Window-read RSS growth |
| --- | ---: | ---: |
|32 MiB|35.578 MiB|3.625 MiB|
|128 MiB|131.727 MiB|3.672 MiB|

Both use fixed120s chunks and60s overlap. These are synthetic zero-valued raw-cache
I/O probes, explicitly not field recordings, media acquisitions or full-pipeline
memory measurements. The operating system manages its filesystem cache; this
measures the iterator's process-resident sample buffers. Consumer results, event
records and plots have separate memory costs.

The Linux regression uses a128MiB sparse cache and samples live VmRSS in a fresh
child during iteration, with a32MiB growth budget. It also verifies complete end
coverage and zero checksum. Baseline intake module from63d620f was copied into
an isolated package overlay, without altering the working tree. The new test
fails on that baseline (regression-before.log) and passes with the window reader.
The live-RSS test is committed in975da54; the test source and production bytes
used by the full-suite run are preserved at that tree.

Checks:

- All5 intake tests pass in1.66s, including actual MP3/WAV timing and channel tests.
- Full current worktree suite: **200 passed, 6 subtests passed in38.07s**.
- A replay of the previously evaluated canonical six-event cache produces an
  exactly identical complete event list (same semantic SHA256). No threshold
  tuning; this is an I/O regression, not a new held-out or location result.

Exact commands use the shared environment and actual worktree source:

```bash
PYTHONPATH=results/baseline-package /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q tests/test_intake.py::test_chunk_iterator_does_not_retain_recording_sized_rss --basetemp=results/pytest-cache-memory-proc-before
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q tests/test_intake.py --basetemp=results/pytest-cache-memory-proc-after
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q --basetemp=results/pytest-cache-full-suite
```

The before overlay contains unmodified baseline intake.py from git63d620f plus
__init__.py/contracts.py. The after tests run the normal package. measure.py is
the separately executed fixed-window RSS probe; create sparse zero caches of the
recorded sizes and pass the path as its sole argument. Input cache binaries and
environments are deliberately not committed. receipt.json includes source hashes
and the before/after values; all failures and successful logs are preserved.
