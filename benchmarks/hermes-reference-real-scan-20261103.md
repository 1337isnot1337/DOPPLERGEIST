# Real Cessna reference: scanner-only harmonic ambiguity

[Palawan Skies Aviation's Cessna 421 takeoff](https://www.youtube.com/watch?v=DqZ2411R1ys)
is a real-video lead also discussed in the [Hermes reference](https://github.com/mojomast/hermes-aircraft-doppler-geolocation#real-world-test-v011).
The uploader identifies Puerto Princesa Airport and mentions glitches from video
stabilization; the precise microphone position, absolute recording clock, and
whether the audio has been edited are not independently established. Hermes
reports a manually selected Doppler fit, not a verified geolocation.

On 2026-11-03 the automatic scanner at source revision `15037c2` processed a
51.444-second audio-only MP3 excerpt, SHA-256
`8a11d340cf0402c86c4863a1435787b6bd0f4efde55583e42ab833815413b6e0`.
It proposed two separately labeled groups over the same 29–51 s interval,
one at approximately 85–101 Hz and one at 129–150 Hz. Their 34 exactly aligned
ridge samples have a median high/low ratio of 1.5025; the 90th-percentile
fractional deviation from 3:2 is about 1.50%. A visual spectrogram shows a
prominent descending harmonic family. These observations are consistent with
one pass split into related ridges, but do not prove aircraft identity or
independent event count. The earlier, steeper portion of the visible trace is
not included in the two reported 29–51 s ridges.

This is a **development and ambiguity case**, not a held-out accuracy test. No
flight matching or geolocation was run on it. The original MP3, scanner JSON
and local review plot are retained in
`/home/cinna/.local/state/dopplergeist-hermes-followup-20261103/`; media is not
committed. The reference-specific download used a temporary YouTube exception,
which was removed immediately afterward.
