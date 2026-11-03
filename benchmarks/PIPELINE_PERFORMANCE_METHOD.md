# Recorded pipeline performance

The measured baseline is main `d51a31073c03fa56c29819e4709664b329ed4535`. The optimized public revision is `57445622181b3b27e4c445ee801024bd318a2739` in [PR #277](https://github.com/1337isnot1337/DOPPLERGEIST/pull/277).

The local tested revision `90989d26cb5d6183551607e4bb516a1d461ca291` has the same Git tree, `401ee10595b807a97fa2ddac37bac52088a948ab`. The version includes [PR #256](https://github.com/1337isnot1337/DOPPLERGEIST/pull/256), [PR #266](https://github.com/1337isnot1337/DOPPLERGEIST/pull/266), native index extraction, conservative distance bounds, and scoring call reuse.

After timing, upstream confidence fix `5329d7e` passed four exact saved-decision replays. These runs did not enter the changed ambiguity check. The timing results remain tied to the revision above.

## Results and scope

| Recorded workload | Baseline wall seconds | Current wall seconds | Speedup | Equality gate |
| --- | ---: | ---: | ---: | --- |
| Complete regional HTTP receipt, three-pair median | 57.8154 | 47.5311 | 1.216× | Exact scientific JSON, ledger, PCM, CSV values, and pixels |
| Dense clock partition, three-pair median | 35.0916 | 20.2684 | 1.731× | Exact scored candidates, ranking, and retention. Separate gates prove early-work reductions |
| Fresh index query, three-pair component median | 6.57094 | 6.09225 | 1.079× | Every field of 4,694 real tracks exact |

Complete HTTP CPU time falls from 57.6234 to 47.0864 seconds. Receipt latency falls 17.79%, and CPU time falls 18.29%.

The dense replay reduces CPU time from 35.0192 to 20.2260 seconds. Its lifetime peak RSS falls from 459.875 to 335.527 MiB.

The regional HTTP replay uses 17 measured ridges in 15 groups. Its tiles have no clock partitions, so the partition-query optimization is inactive.

The dense replay uses one explicit anchor partition and 16 groups. It excludes imports, discovery, terrain, and refinement. Its ratio cannot represent complete uploads.

The regional archive excludes known jets and has incomplete coverage. Receiver coordinates and narrow recording windows come from historical fits. These measurements establish computational performance, not location accuracy.

[The result file](results/pipeline-optimization-20261103.json) retains individual timings, controls, counters, and the initial comparator difference.

## Reproduce the measured controls

Start in the current PR #277 checkout, which includes the comparator metadata declaration. Use Linux, Git, GCC, FFmpeg, GitHub CLI, and one Python environment for both sources. The measured interpreter was Python 3.12.14. Use new baseline, input, and output paths for each experiment.

```sh
set -euo pipefail
perf_root="$(pwd -P)"
perf_baseline="$perf_root/../dopplergeist-performance-baseline"
export CC=gcc OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export DOPPLERGEIST_RIDGE_BACKEND=auto DOPPLERGEIST_ACOUSTIC_BACKEND=auto
export DOPPLERGEIST_CPA_BACKEND=auto DOPPLERGEIST_INDEX_BACKEND=auto
python -m pip install 'setuptools>=68'
python -m pip install --editable '.[test]'
python setup.py build_ext --inplace
git fetch origin d51a31073c03fa56c29819e4709664b329ed4535
git worktree add --detach "$perf_baseline" d51a31073c03fa56c29819e4709664b329ed4535
(
  cd "$perf_baseline"
  python setup.py build_ext --inplace
)
python scripts/restore_artifacts.py --bundle data-source --bundle data-adsb-derived --bundle data-terrain
PYTHONPATH="$perf_baseline/src" python "$perf_baseline/scripts/prepare_reference_upload.py" \
  --data-root data --output benchmark-inputs
PYTHONPATH="$perf_baseline/src" python "$perf_baseline/scripts/benchmark_prepared_measurements.py" prepare \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --index benchmark-inputs/reference-region.sqlite --reference-report evidence/results/reference-local/report.json \
  --full-day --max-tracks 2000 --max-samples 500000 --max-candidates 20000 --top-k 100 \
  --anchor-window-s 1788864888.7151732 1788865236.7214916 --include-track-query \
  --output benchmark-inputs/dense-query.json
ffmpeg -n -nostdin -v error -i data/source/reference-recording.wav -map 0:a:0 -vn \
  -map_metadata -1 -ac 1 -ar 48000 -c:a libmp3lame -b:a 96k benchmark-inputs/reference.mp3
python - <<'PY'
import json
from pathlib import Path
root = Path('benchmark-inputs')
operator = json.loads((root / 'operator.json').read_text())
operator['search_workers'] = 1
request = json.loads(Path('benchmarks/reference-regional-upload-request.json').read_text())
for name, value in (('regional-operator.json', operator), ('regional-request.json', request)):
    with (root / name).open('x') as output:
        output.write(json.dumps(value, indent=2) + '\n')
PY
perf_cpu="$(python -c 'import os; print(min(os.sched_getaffinity(0)))')"
export PYTHONPATH="$perf_root/src"
python scripts/benchmark_real_index_decode.py --fixture benchmark-inputs/dense-query.json \
  --baseline-source "$perf_baseline/src" --repeats 3 --output benchmarks/runs/index-decode.json
taskset -c "$perf_cpu" python scripts/benchmark_prepared_measurements.py compare \
  --fixture benchmark-inputs/dense-query.json --baseline-source "$perf_baseline/src" --current-source src \
  --include-track-query --clock-partition-query --repeats 3 --timeout-s 600 \
  --require-current-native --require-current-native-acoustic --require-current-native-cpa \
  --output benchmarks/runs/dense-replay
for perf_pair in 1 2 3; do
  perf_arms="baseline current"
  if [ "$perf_pair" = 2 ]; then perf_arms="current baseline"; fi
  for perf_arm in $perf_arms; do
    perf_source="$perf_baseline/src"
    if [ "$perf_arm" = current ]; then perf_source="$perf_root/src"; fi
    python scripts/benchmark_real_regional_upload.py --source "$perf_source" \
      --audio benchmark-inputs/reference.mp3 --request benchmark-inputs/regional-request.json \
      --operator benchmark-inputs/regional-operator.json --reference-wav data/source/reference-recording.wav \
      --expected-audio-sha256 707083f0344823eeea7f130faec6c22b6628b8b9fea04d026915d93df9a07b15 \
      --threads 1 --cpu "$perf_cpu" --timeout-s 600 --output "benchmarks/runs/http-$perf_pair-$perf_arm"
  done
  python scripts/benchmark_real_regional_upload.py \
    --compare "benchmarks/runs/http-$perf_pair-baseline" "benchmarks/runs/http-$perf_pair-current" \
    --output "benchmarks/runs/http-$perf_pair-comparison.json"
done
```

Baseline fixture preparation is essential. Each preparation script prepends its own source directory. A baseline `PYTHONPATH` alone cannot redirect the optimized preparation script.

The historical MP3 has fixed 17-ridge and 15-group controls. Different encoder bytes require a separate `--allow-new-encoding` experiment and cannot inherit these measurements.

The dense comparison requires native ridge, acoustic, and CPA execution in current runs. Baseline native ridge was available, but its successful fit count was unmeasured.

## Exactness and interpretation

The HTTP comparator checks complete scientific JSON, all logical ledger rows, decoded PCM, CSV values, and image pixels. Only declared implementation, path, and performance metadata differ.

The first raw HTTP comparison found only new `configuration/runtime/cpa_backend` metadata. The final comparator declares this exact implementation field alongside existing backend metadata. Scientific fields remain in the comparison.

Dense raw `identical_results` is false because early-work diagnostics change. Required gates are `identical_scored_candidates_rankings_and_retention`, `performance_timing_eligible`, deterministic repeats, and successful `clock_partition_query_verification`.

All 16,101 scored candidates and 100 retained candidates remain exact. Fifty-eight removed unsupported reports lie wholly outside the feasible emission interval. Four reports remain unchanged.

HTTP and dense runs use fresh processes, one numerical thread, and CPU 0. The native-index component uses fresh index objects in one process, unpinned on CPUs 0–8.

Filesystem caches remain uncontrolled. Component gains cannot be added or multiplied into pipeline gains. Profilers identify expensive functions but do not supply reported timings.

Two experiments were excluded from the delivered runtime. A stronger Bezier-bound sieve cost more than it saved. A refinement cache produced no repeatable gain across three pairs; a simpler nominal-only version saved less than 1% in its screening pair. Fewer calls or fewer selected tracks alone do not establish a speedup.

Read selected tests before execution. Use archived observations and restored real inputs. The repository forbids synthetic-data test suites.
