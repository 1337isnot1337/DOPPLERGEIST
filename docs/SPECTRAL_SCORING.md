# Shared-clock spectral scoring

`spectral_matching` is a development adapter for the video's contrast-based
curve scoring. It is not yet connected to the automatic search or decision.

`measure_spectral_event(recording, event)` extracts a measured spectrogram from
the decoded recording around an automatically proposed event. Its default
expansion and band follow the existing spectral-context protocol. It processes
one event at a time and rejects an STFT exceeding `max_stft_bins`; callers must
also bound storage if they retain several spectra.

`score_spectral_association` evaluates a supplied event-group/flight association
on one common recording-start grid, sweeping each event's source frequency with
the existing emission-time `event_score`. It sums per-event contrast scores and
returns the event indices and flight IDs alongside the result. A score is only
comparable to another score on the same event-group set and spectral settings.
Unvisited associations, alternative subsets and unsupported frequencies or
trajectories are not resolved by this score. Unknown clock trials and work-limit
exhaustion remain explicit; `status: scored` does not imply all trials or the
national search were complete. These scores are not probabilities.

The adapter neither selects candidate flights nor changes location decisions.
Integration must account for all retained and omitted competitors under a
spectral-compatible retention bound, define comparisons across event subsets,
and retain conservative inconclusive outcomes. Additional measured harmonics
are not yet jointly scored. A source-informed regional real-audio comparison is
only a software check; a real whole-recording, truth-separated search remains
necessary to establish the requested outcome.

For a local real-audio software check, provide the prior regional run, its
trajectory Parquet and type database, and an actual completed automatic job:

```bash
PYTHONPATH=src python scripts/check_real_spectral_adapter.py \
  /path/to/reference-results /path/to/tracks.parquet \
  /path/to/type-database.csv /path/to/automatic-job
```

The check compares legacy brightness scoring with five common-clock trials,
checks one real-event subset, work limits and missing-track handling, and
extracts a spectrum from the first discovered event in the actual job. The
regional input is source-informed; it is not a location benchmark.
