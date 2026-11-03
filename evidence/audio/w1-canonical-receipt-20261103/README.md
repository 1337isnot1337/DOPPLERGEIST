# Independent frozen audio-stage replay

The primary's canonical independently rendered 3/4/6-event MP3s were replayed
through frozen detector47261fe with unchanged contrast2.5 settings. All13 labelled
events match at the existing event-window IoU>=0.3:3/3,4/4,6/6, with no misses,
false alarms or processing failures. Later passes are retained. Total subprocess
time21.533s; maximum per-case peak RSS383.461MiB. No production code changed.

All three complete discovery JSON artifacts are **byte-identical** to the
canonical artifacts published in PR #60 at26a5bff74e9aba664e5f951cca8fa26f26e3eaf0.
receipt.json records both hashes, per-module producer hashes, input hashes,
resources and semantic equality checks. Canonical full JSON/CSV/PNG evidence is
at evidence/verification/multi-event-20261103/events-{3,4,6}/discovery/. This compact
receipt links that evidence; full independent outputs remain locally under the
path recorded in receipt.json and local branch swarm/w1-multi-evidence@c696d00.

Only verified byte-identical opaque MP3s and label-free requests were passed to
the producer subprocesses. No tracks, expected counts, event hints, coordinates,
renderer files or truth labels entered discovery. All predictions completed
before a separate process opened labels to evaluate windows. Generator source
and exact input hashes are pinned in input-provenance.json. This is a trusted
producer/input-separation check, not adversarial filesystem-namespace sealing.

Exact runner command in the original W1 worktree:

```bash
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python scripts/run_benchmark.py results/w1-canonical-multi-1f03425/inputs/manifest.json --output results/w1-canonical-multi-1f03425/predictions -- /usr/bin/env PYTHONPATH=/home/cinna/dopplergeist-w1-gap-plots/src /home/cinna/aircraft-audio-geolocation/.venv/bin/python /home/cinna/dopplergeist-w1-gap-plots/scripts/discover_benchmark_case.py '{request}' '{output}'
```

report.json is the post-run window evaluation at IoU0.3; its100/500/1000m policy
annotation has zero eligible location cases. Every adapter result intentionally
says inconclusive/discovery_only. This does not test flight association, national
search, an actual upload, location accuracy or a sealed real holdout. Those gates
remain separate. No raw audio, cache, environment or truth coordinate is added.
