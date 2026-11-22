# Notes from the *field.*

[Canonical page](https://itsdavis.com/DOPPLERGEIST/examples.html)

An aircraft heard by a phone in California. Forty recordings scanned for moving tones. Five field recordings with uncertain clocks. Each experiment tests a different part of the idea.

[Livermore](https://itsdavis.com/DOPPLERGEIST/examples.html#livermore)[Field results](https://itsdavis.com/DOPPLERGEIST/examples.html#results)[Pitch curves](https://itsdavis.com/DOPPLERGEIST/examples.html#frequency)[Discovery](https://itsdavis.com/DOPPLERGEIST/examples.html#discovery)[Candidate maps](https://itsdavis.com/DOPPLERGEIST/examples.html#map)

## The Livermore recording

The automatic upload took the whole MP3, a city-area search boundary and an approximately ten-second start window. It received no flight ID, frequency band or hand-picked event. This historical run searched all aircraft types. Current searches use confirmed non-jets.

Automatic MP3 search↗

[![Automatic real MP3 analysis with the observed Doppler curve and ranked locations on a Livermore satellite map](https://itsdavis.com/DOPPLERGEIST/site-media/livermore-automatic-mp3.webp)](https://itsdavis.com/DOPPLERGEIST/site-media/livermore-automatic-mp3.png)

Recorded audio and ranked candidates. The run remained inconclusive.

### Reading the result

Of 466 nearby aircraft, the search associated the recorded passage with a track and ranked 105 candidate locations. The top point lay 476 m from a reference inferred from other flight tracks. Some trajectories exceeded the model’s limits, so the run returned an inconclusive decision. [Experiment and ranking ↗](https://github.com/1337isnot1337/DOPPLERGEIST/blob/main/docs/LIVERMORE_DEMO.md#all-aircraft-archive-mp3-ranking)

Configured search↗

[![Configured Livermore search showing a recorded flyover and a bounded map of candidate microphone positions](https://itsdavis.com/DOPPLERGEIST/site-media/livermore-configured.webp)](https://itsdavis.com/DOPPLERGEIST/site-media/livermore-configured.png)

A separate replay supplied one track, a time interval and a frequency band. Its top point fell 481 m from the same inferred reference. The replay also remained inconclusive.

## What the field tests found

The experiments range from guided replays to automatic discovery. Independent blind accuracy on real recordings remains an open measurement.

### Two flyovers, one recorder

**43.86 m**

With source-informed events and geographic bounds, the leading point fell this far from an approximate public reference. The model left the result inconclusive.

[Read the field report ↗](https://github.com/1337isnot1337/DOPPLERGEIST/blob/main/docs/verification/CLEAN_REPLAY.md)

### Smartphone discovery

**36 of 40**

The full-recording detector proposed acoustic groups in 36 files. Each group is a lead for flight matching. Aircraft identities and microphone locations require separate evidence.

[Read the field report ↗](https://github.com/1337isnot1337/DOPPLERGEIST/blob/main/docs/AUDIO_DISCOVERY.md)

### Public field recordings

**5 recordings**

Three searches returned rankings, all outside 1 km of the reported sites. Two returned no candidate. The precise microphone positions and recording clocks were unconfirmed.

[Read the field report ↗](https://github.com/1337isnot1337/DOPPLERGEIST/blob/main/docs/PUBLIC_RECORDING_EXPERIMENT_2026-11-03.md)

### NASA and WSU recordings

**Mixed outcomes**

Measured flight trajectories offered a check on the workflow. Detection varied across the recordings and the evaluations yielded no validated automatic location.

[Read the field report ↗](https://github.com/1337isnot1337/DOPPLERGEIST/blob/main/docs/verification/WORKER_E2E_2026-11-03.md)

## How to read a pitch curve

Read left to right for time and bottom to top for frequency. A bright band follows energy in a narrow range of pitches. Compare its bend with the model laid over the recording.

The measured ridge↗

[![Recorded aircraft Doppler ridge and a fitted straight-pass curve](https://itsdavis.com/DOPPLERGEIST/site-media/measured-event.webp)](https://itsdavis.com/DOPPLERGEIST/site-media/measured-event.png)

A moving tone in the recording, with a fitted straight-pass curve.

The flight-path model↗

[![Observed aircraft spectrogram with a best-fitting sound propagation model](https://itsdavis.com/DOPPLERGEIST/site-media/physical-model.webp)](https://itsdavis.com/DOPPLERGEIST/site-media/physical-model.png)

A trajectory-based prediction over the recorded spectrogram.

A second passage↗

[![Second recorded flyover with cyan Doppler model over the descending frequency ridge](https://itsdavis.com/DOPPLERGEIST/site-media/track-overlay.webp)](https://itsdavis.com/DOPPLERGEIST/site-media/track-overlay.png)

A flight-path prediction laid over another recorded frequency ridge.

## One pass can leave many traces

A propeller can produce several harmonics that bend together. Grouping those lines keeps one noisy flyover from counting as several independent sightings.

Across the recording↗

[![Whole-recording discovery showing candidate moving-frequency traces over recording time](https://itsdavis.com/DOPPLERGEIST/site-media/discovery-overview.webp)](https://itsdavis.com/DOPPLERGEIST/site-media/discovery-overview.png)

Moving-frequency proposals found by the detector; proposals are not confirmed aircraft.

Grouping the traces↗

[![Frequency traces grouped into a canonical acoustic episode over 60 seconds](https://itsdavis.com/DOPPLERGEIST/site-media/acoustic-families.webp)](https://itsdavis.com/DOPPLERGEIST/site-media/acoustic-families.png)

Related tones are grouped so harmonics do not count as independent flyovers.

## What a candidate map shows

Each point marks a possible microphone position. Color shows how well the model fits the evidence there. The star marks the highest score. Similar scores at distant points leave the location ambiguous.

The candidate map↗

[![Geographic grid colored by location fit score, with the highest-scoring position marked by a red star](https://itsdavis.com/DOPPLERGEIST/site-media/location-scores.webp)](https://itsdavis.com/DOPPLERGEIST/site-media/location-scores.png)

Color encodes fit score, not location probability.

[Browse the source figures ↗](https://github.com/1337isnot1337/DOPPLERGEIST/tree/main/evidence)

[Explore the method →](https://itsdavis.com/DOPPLERGEIST/how-it-works.html)
