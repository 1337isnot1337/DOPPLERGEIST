# Experimental coherent audio proposals

The ordinary per-frame peak linker can miss a continuous weak curve. Issue
[#341](https://github.com/1337isnot1337/DOPPLERGEIST/issues/341) evaluates an
additional whole-file detector using
[digitalis-p/doppler-locate](https://github.com/digitalis-p/doppler-locate).
The tested reference revision is `ed84e0f`, under its MIT license. This optional
research script requires that package and its dependencies in the executing
Python environment; the default DOPPLERGEIST installation is unchanged. Python
3.12 was used for the reference detector.

From this checkout, with an installed reference package:

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python scripts/discover_coherent_audio.py original.mp3 \
  --output coherent-events.json --workers 2
```

Alternatively, add the reference checkout's `src` to `PYTHONPATH`. The script
processes the entire original recording with the reference template bank. It
captures actual measured ridge samples, skips unused straight-pass profile-range
calculations, and exports the existing detected-event schema. It reuses the
reference's 40-point and 1% relative-fit-residual requirements without its hard
aircraft/close type gate. Slow and nearby proposals remain eligible. Duplicate
and harmonic ridges are grouped; their count is not an independent aircraft count.

These are acoustic proposals. They can include ground traffic, and short curves
can fit several unrelated archived flights. Neither a low residual nor ADS-B
presence establishes audibility. Use the historical physical matcher and shared
timing; never present these outputs alone as locations. This script does not
change `analyze`, its discovery defaults, or existing job checkpoints.

The regression fixture contains only measured frequencies/times derived from
[XC1092456](https://xeno-canto.org/1092456) by Valerie Heemstra, with the public recording link retained
for attribution. It contains no audio, coordinates or flight IDs. The original
recording is [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/);
see the source page for the recordist attribution.
