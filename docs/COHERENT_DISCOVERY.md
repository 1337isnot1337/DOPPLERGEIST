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

## Fixed real-clip development and held-out check

From the existing seeded AeroSonicDB sample, take the first two aircraft-labeled
and first two background-labeled clips per publisher location for development,
then the next two per class/location as a held-out set. No labels, flight IDs or
locations enter the detector. The complete case outcomes are in the
[24-row table](../benchmarks/coherent-proposals-341-20261104.csv).

| Partition and publisher label | Clips | Ordinary discovery | Coherent adapter | Union |
| --- | ---: | ---: | ---: | ---: |
| Development aircraft | 6 | 2 | 3 | 3 |
| Held-out aircraft | 6 | 3 | 3 | 3 |
| Development background (duration-ineligible) | 6 | 0 | 0 | 0 |
| Held-out background (duration-ineligible) | 6 | 0 | 0 | 0 |

Counts mean clips with proposals, not confirmed aircraft or independent events.
The initial unrestricted reference-trace experiment proposed on 5/6 development
aircraft clips and 1/6 backgrounds; the existing quality rules discard short or
noisy traces. The final adapter adds one development clip and no held-out clip.
All background clips are 10 s, while aircraft clips are 60 s. With a 1 s FFT
and 0.25 s hop, 10 s supplies at most 37 frames, below the 40-point gate. The
ordinary backend also requires 12 s. Thus the background zeros are structurally
guaranteed and provide **no false-alarm evidence**. Background rejection remains
unvalidated. These small, source-defined aircraft strata do not establish
improved general recall and do not justify changing normal upload defaults. See the
[AeroSonicDB source and sampling report](../benchmarks/aerosonic-scanner-survey-20261103.md).

All twelve development replays preserved the reference detector's measured
traces exactly while omitting profile ranges. Summed wall time was 185.72 s
with reference profiles and 172.24 s for the adapter, but the median paired
ratio was 1.031. These single passes had different system load; there is no
consistent measured speedup claim. Neither this clip test nor the Michigan
regression establishes a location.

The standalone CLI also processed the entire 819.4 s
[XC891053 Kane County recording](https://xeno-canto.org/891053) in 146.09 s,
exporting seven proposal groups from nine refined traces. The exact location
reference remained withheld. This checks actual whole-file script execution,
not seven aircraft identities, a localization, or total search time.
