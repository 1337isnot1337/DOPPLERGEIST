# Decoder startup errors stay distinct from media rejection

The upload verifier reported a valid six-event MP3 labelled invalid_media when
ffprobe exited127 because a runtime-library symlink was unavailable in its
namespace. The original failure remains historical. This follow-up reproduces
the error-classification boundary with valid WAV bytes and private executable
stubs, without altering installed binaries or rerunning that namespace job.

| Failure | Original ffprobe result | Original ffmpeg result | Fixed result |
| --- | --- | --- | --- |
|Startup status127|invalid_media|decode_failed|decoder_unavailable|
|Executable permission denied|uncaught PermissionError|uncaught PermissionError|decoder_unavailable|
|Ordinary media rejection status1|invalid_media|decode_failed|original codes retained|

The baseline intake module fromfcbe513 was copied into an isolated package
overlay; the working tree was not rolled back. Current six protocol cases yield
4 failed regressions and2 passing existing-media controls on that baseline.
The fixed reader at4913fc4 passes all11 intake tests, including actual MP3/WAV
timing and memory checks. Full current worktree:225 tests plus6 subtests pass in
90.51s. Tests verify input byte preservation and no finalized cache after each
failure. This is a controlled classifier test, not a field acquisition or a claim
that an actual installed library was removed locally.

Exact commands:

```bash
PYTHONPATH=results/baseline-decoder-package /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q tests/test_intake.py::test_decoder_startup_and_media_failures_are_distinct --basetemp=results/pytest-decoder-baseline-final
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q tests/test_intake.py --basetemp=results/pytest-decoder-startup-final
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q --basetemp=results/pytest-decoder-full-suite
```

The overlay contains unmodified baseline intake.py from Git plus current
__init__.py/contracts.py. Test stubs use a process-local private PATH; pytest
restores it after each case. POSIX startup126/127 and executable launch OSErrors
reuse the existing decoder_unavailable reason. Decode algorithms, input samples,
metadata, discovery settings and score/decision rules are unchanged. A real
corrupt/unsupported media rejection still has its original classification.
