# Hermes reference audit

User-supplied reference:
[mojomast/hermes-aircraft-doppler-geolocation](https://github.com/mojomast/hermes-aircraft-doppler-geolocation),
pinned on 2026-11-02 at `2c3ed20577bcce29058d73422dd4f85392d04c24`.
Its LICENSE is MIT, copyright Kyle Durepos. No plugin installation or source-code
copy into our implementation was performed. The reference was cloned under an
ignored experiment directory for inspection and its own offline tests.

## Relevant findings

- The [README](https://github.com/mojomast/hermes-aircraft-doppler-geolocation/blob/2c3ed20577bcce29058d73422dd4f85392d04c24/README.md)
  explicitly distinguishes its independent reconstruction from the video's
  unreleased code. It reports real acoustic tests with manual windows/bands,
  but no real-flight localization validation or scripted acquisition/terrain/grid
  workflow. Those recordings have no established sample-zero clock, so they do
  not resolve our independent real-corpus gate.
- Its synthetic example includes the true observer exactly on its 200 m candidate
  grid. A first-ranked point with 0 m error therefore does not establish off-grid
  precision, automatic national recall or uncertainty calibration. Our independent
  synthetic generator keeps the recorder off the search grid, with truth separate.
- The documented unknown-clock single-event error is approximately 1.4 km along
  the track. This is a useful ambiguity case, consistent with requiring independent
  flyovers and locked relative timing before accepting our default precision target.
- [score_candidates.py](https://github.com/mojomast/hermes-aircraft-doppler-geolocation/blob/2c3ed20577bcce29058d73422dd4f85392d04c24/skills/aircraft-doppler-geolocation/scripts/score_candidates.py)
  preserves emission-time radial velocity and reception delay. It uses local
  flat-earth coordinates, one global CPA and RMS misfit where **lower is better**.
  Our WGS84/gap-split/multiple-approach higher-is-better robust loss is a different
  score. Thresholds and confidence interpretations must not be copied between them.
- Its scorer evaluates whichever observed samples overlap track support and only
  requires five samples. A direct probe with 100 observed constant-frequency
  samples and support for only five returns zero RMS. This is not a valid complete
  event association. Our decision requires >=95% support, checked independently of
  raw spectral rank. No probability or parameter stderr substitutes for this gate.
- Its synthetic renderer reuses the scorer's local-coordinate helper. It still
  transports emission phase to reception time, but does not replace independent
  analytic/gap/Unix-clock tests or the separate scientific replays in this project.

## Executed checks

```bash
git clone --depth 1 https://github.com/mojomast/hermes-aircraft-doppler-geolocation.git results/references/hermes
cd results/references/hermes
/home/cinna/aircraft-audio-geolocation/.venv/bin/python -m unittest discover -s tests -v
```

Result: **6 tests passed in 16.654 s**, including its synthetic location test and
noise rejection. Original source remained clean. The direct scorer probe returned
`(0.0, -0.0, 110.0)` for 5/100 supported samples. Outputs are retained locally as
`results/references/hermes-test-output.txt` and `hermes-partial-support.json`.
These are checks of the reference package, not additional DOPPLERGEIST pipeline
or independent real-data successes.
