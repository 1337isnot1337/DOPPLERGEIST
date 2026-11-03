# CI verification, 2026-11-02

This note records the configured-methodology replay at commit
[`3bb51abc5c01d2cf27ada89740a800c9d79a28e3`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/3bb51abc5c01d2cf27ada89740a800c9d79a28e3),
from [Actions run 41553347143](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41553347143).
The note date uses America/Chicago; the job logs use 2026-11-03 UTC.

## Completed synthetic job

[Job 125646110867](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41553347143/job/125646110867)
completed successfully. Its logs show a full-history Git checkout (`fetch-depth: 0`),
sparse checkout disabled, and the exact commit above. Installation used
`python -m pip install -e . pytest`; `python -m pip check` reported no broken
requirements. The test command
`python -m pytest -q --junitxml=results/ci-environment/pytest.xml` reported
**53 tests and 6 subtests passed in 2.23 s**.

The actual replay command was:

```bash
python scripts/ci_checkpoint_replay.py --output results/ci-synthetic --case-timeout-s 600
```

Both configured cases completed through the real CLI and passed the 100 m
horizontal WGS84 geodesic threshold. These are this commit's measured results;
historical checkpoint results remain unchanged.

| Case | Error, m | Flight IDs verified by evaluator | Clock error, s |
| --- | ---: | --- | ---: |
| Two events, unknown recording start | 15.395598179748822 | `true-A`, `true-B` | +0.06380653381347656 |
| Known-time minute | 40.87444831462204 | `true-A` | +0.5 |

Clock error is estimated recording start minus generator truth. The known-time
configuration permits a ±0.5 s sweep and selected the positive endpoint; its
clock was not recovered with zero error. The result table is printed in the
completed job log.

### Installed environment

The setup/install logs record Ubuntu 24.04.5, CPython 3.12.15, pytest 9.2.0,
and Ubuntu ffmpeg package `7:6.1.1-3ubuntu5`. Direct Python dependencies were:

| Package | Version |
| --- | --- |
| NumPy | 2.5.4 |
| SciPy | 1.18.1 |
| pandas | 3.1.0 |
| soundfile | 0.14.0 |
| pyproj | 3.8.0 |
| rasterio | 1.5.2 |
| matplotlib | 3.11.2 |
| requests | 2.34.2 |
| pyarrow | 26.0.0 |

The job saved `ci-environment/requirements-resolved.txt`, its checkout commit/status,
ffmpeg version, JUnit report, and `ci-synthetic/acceptance.json` in
[artifact 13191599846](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41553347143/artifacts/13191599846).
The upload log records 77 files and a 21,674,727-byte ZIP. Both the upload log
and artifact API report this ZIP SHA-256:

```text
38020418cefee4cd37b84b41717376b53077283d15381e912529af342dd1823f
```

This checksum was read from GitHub's records; the ZIP was not independently
downloaded and rehashed for this note. GitHub reports expiry on 2026-12-03 UTC.

## Truth separation and scope

The [runner at the tested commit](https://github.com/1337isnot1337/DOPPLERGEIST/blob/3bb51abc5c01d2cf27ada89740a800c9d79a28e3/scripts/ci_checkpoint_replay.py)
copies the synthetic generator unchanged, moves its truth file outside the search
input directory, runs both CLI searches, and then reads truth for evaluation.
It checks that the declared CLI input paths do not include the truth file and
checks each report's implementation digest against its frozen source snapshot.
This is procedural separation: the search process's account can still access
the evaluation directory.

The replay uses configured event windows and frequency bands. It does not exercise
automatic event discovery, MP3 upload, the product API/UI, or national search.
These synthetic results establish no independent real-recording accuracy claim.

## Completed regional job

[Regional job 125647085176](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41553347143/job/125647085176)
completed successfully at the same commit. The restore logs confirm verification
and restoration of 68 files against the committed manifest: 54 source files,
8 ADS-B-derived files, and 6 terrain files. The commands were:

```bash
python scripts/restore_ci_checkpoint.py --destination . --receipt results/ci-restore.json
python scripts/ci_checkpoint_replay.py --output results/ci-regional --real-config data/source/reproduce-local.json --case-timeout-s 900
```

The `reference-regional` result reports **43.85847078233993 m** horizontal WGS84
geodesic distance from the public-platform reference and `passed: true` against
the configured 100 m threshold. The restore receipt and replay outputs are in
[artifact 13193708320](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41553347143/artifacts/13193708320),
a 15,970,633-byte ZIP. The upload log and artifact API report SHA-256:

```text
5c6e5cd64c9ce8446b559607d07ad1a2453988c370f805bb07451cfaf4a3b1ac
```

This ZIP also was not independently downloaded and rehashed for this note.
The result remains source-informed: event settings and geographic bounds were
supplied, the mapped public-platform coordinate is not surveyed microphone truth,
and the recording clock has not been independently established. Independent real
and nationwide acceptance remain unverified. See [PROGRESS.md](PROGRESS.md) and
[the final acceptance issue](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13).
