# Evidence-based next steps

For an existing local job, run:

```bash
python scripts/explain_job.py /path/to/job-directory
```

The command reads `result.json` and, when present, `decision.json` in that job.
It emits JSON suggestions with pointers to the evidence behind each observation.
It does not change the saved job, scores, candidates or decision. An empty list
means no supported suggestion was derived, not that the result is conclusive.

Suggestions are conditional, and their benefit is not measured. This first
increment covers missing recording time, no detected events, too few independent
flyovers, missing flight data, a wall-time limit and reported competing modes
when the corresponding evidence is present. It does not rank recommendations,
run counterfactuals, or establish whether more audio or a narrower time window
will resolve ambiguity. The existing API and browser UI do not yet display this
output. End-to-end examples beyond the missing-clock case and the required
positive and negative counterfactual controls remain open in issue #63.
