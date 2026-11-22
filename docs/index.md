# The geography of a *flyover.*

[Canonical page](https://itsdavis.com/DOPPLERGEIST/)

A passing plane leaves a pitch curve in a recording. DOPPLERGEIST compares that curve with historical flight tracks to work out where the microphone could have been.

[Explore the field notes →](https://itsdavis.com/DOPPLERGEIST/examples.html)[Run locally](https://itsdavis.com/DOPPLERGEIST/#run)

Livermore, CaliforniaN784MB / R04

Frequency (Hz)

Show measured ridge

400300200100

![An 85-second spectrogram of the Livermore recording. Bright bands descend together as the aircraft passes the microphone.](https://itsdavis.com/DOPPLERGEIST/site-media/livermore-spectrum.webp)

0 s20406080

0:00 / 1:25

Playback is unavailable. [Open the MP3](https://itsdavis.com/DOPPLERGEIST/site-media/livermore-r04.mp3).

Recorded by [Praveen Pathak](https://doi.org/10.5281/zenodo.23424278) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). [Audio and figure credits](https://itsdavis.com/DOPPLERGEIST/site-media/livermore-r04-source.txt).

## One recording. *466 aircraft.*

In Livermore, California, the software scanned a smartphone recording from start to finish. It picked out moving tones, searched the nearby air traffic and returned 105 possible microphone locations.

[Inside the Livermore experiment ↗](https://itsdavis.com/DOPPLERGEIST/examples.html#livermore)

Automatic MP3 search↗

[![Automatic real MP3 analysis with the observed Doppler curve and ranked locations on a Livermore satellite map](https://itsdavis.com/DOPPLERGEIST/site-media/livermore-automatic-mp3.webp)](https://itsdavis.com/DOPPLERGEIST/site-media/livermore-automatic-mp3.png)

Recorded audio and ranked candidates. The run remained inconclusive.

### 476 m

Distance from the first-ranked point to the inferred recording site. The search used a city-sized area and a roughly ten-second clock window. The site was unsurveyed and the result remained inconclusive.

[Read the experiment ↗](https://github.com/1337isnot1337/DOPPLERGEIST/blob/main/docs/LIVERMORE_DEMO.md#all-aircraft-archive-mp3-ranking)

## What makes the *pitch fall?*

Listen as the plane passes. The engine can hold a steady tone while its pitch at the microphone falls. Move the microphone in the model to see how distance changes the shape of that fall.

[Explore the method ↗](https://itsdavis.com/DOPPLERGEIST/how-it-works.html)

The Doppler effectInteractive model

Flyover position

Higher pitch

Approaching · higher pitch

Adjust the model

Aircraft speed

120 m/s

Microphone distance

800 m

## Run it on your *own recording.*

Scan the audio on your own machine. Add a recording-time window to compare what you hear with the flight archive.

[Installation guide ↗](https://github.com/1337isnot1337/DOPPLERGEIST/blob/main/docs/PYPI.md)

### Local browser interface

    pipx install dopplergeist
    dopplergeist serve --jobs jobs --online --max-runtime 14400 --port 8765

Open `http://127.0.0.1:8765`. Use Linux, macOS or WSL with Python 3.11+ and FFmpeg. On Intel Macs, use Python 3.11–3.13.

[Browser workflow ↗](https://github.com/1337isnot1337/DOPPLERGEIST/blob/main/docs/PRODUCT.md)

Preview the local interface

![The local DOPPLERGEIST upload form, with inputs for the recording and its UTC time window.](https://itsdavis.com/DOPPLERGEIST/site-media/local-upload.webp)
