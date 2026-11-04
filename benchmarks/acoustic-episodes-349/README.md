# Real acoustic-episode comparison

See [the engineering report](../../docs/ACOUSTIC_EPISODES_REPORT.md) for the fixed
selection, expectations, measurements, regressions, limits and reproduction.

- `manifest.json`: all 32 actual input identities, public sources, rights and
  processing. Restore media to its relative `path` entries before running.
- `comparison.csv`: all cases, with old/new/wider proposal and child counts,
  union observed time, old-point overlap, time, RSS, output volume and code identity.
- `observations.jsonl.gz`: one JSON object per input, retaining complete baseline,
  new and optional wide discovery observations; no audio. `wide=null` is expected
  only for the hour-long reference, outside the wide arm.

The baseline is 451b67f; the frozen new comparison is 05548ed. Per-case content
hashes, settings and runtime are inside the new artifacts. Failed-check counts
can exceed rejected candidates because a candidate may fail several checks.
The final reporting-only patch exposes separate sustained/brief gate diagnostics;
accepted events/episodes were checked unchanged on the real rich-family clip.

AeroSonicDB is by Downward and Nordby, CC BY-NC 4.0; DEMAND is by Thiemann, Ito
and Vincent, CC BY-SA 3.0; DLR RECORD139 is CC BY 4.0 (see source record and the
existing extraction report). The reference source's redistribution permission
is unestablished. Media are not included. This package contains factual derived
frequency measurements and diagnostics; it makes no aircraft, source-motion,
source-count or localization-accuracy claim.

Inspect the saved measurements with:

```python
import gzip, json
with gzip.open('benchmarks/acoustic-episodes-349/observations.jsonl.gz', 'rt') as f:
    for line in f:
        row = json.loads(line)
        print(row['case_id'], row['new']['counts'])
```

`family-episodes.png` uses AeroSonicDB measurements (Downward and Nordby,
CC BY-NC 4.0). `vehicle-episodes.png` uses DEMAND measurements (Thiemann, Ito
and Vincent, CC BY-SA 3.0). Both show canonical episode plots from the fixed
comparison, with source identity unresolved.
