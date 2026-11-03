# Pinned Hermes comparison

User-supplied reference: [mojomast/hermes-aircraft-doppler-geolocation](https://github.com/mojomast/hermes-aircraft-doppler-geolocation/tree/2c3ed20577bcce29058d73422dd4f85392d04c24),
commit `2c3ed20577bcce29058d73422dd4f85392d04c24`, MIT license, Kyle Durepos.
It is another independent implementation of the public video's method. No donor
code was copied into our implementation in this comparison.

The inspected scripts supply band/window-selected Viterbi ridge tracing, sub-bin
measurement, multistart straight-pass fitting, explicit rejection diagnostics and
emission-time candidate scoring. The README distinguishes real tone detection
from its synthetic location self-test. It does not supply automatic event
discovery, historical flight/terrain acquisition or national search. Its synthetic
test supplies a single known flight and includes the true observer on its grid;
that result cannot establish blind off-grid real localization. Its scorer's
partial-overlap support is less strict than DOPPLERGEIST's full-event support.

Our local comparison command was
`/home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q tests`
in `/home/cinna/dopplergeist-reference-hermes`: **6 passed in 19.64 s**, including
the donor's offline synthetic extraction/scoring test. This is a reference-code
check, not DOPPLERGEIST automatic upload or national accuracy acceptance. The
integration board records another worker's retained full donor replay; do not
repeat it merely to duplicate green checks.

A useful remaining audio experiment is a seeded dynamic-programming continuation
for weak ridges, reusing our existing audio.trace_ridge. Any such fallback must
select its own seeds/bands from the recording, reject unsupported noise paths,
and be evaluated at fixed settings. A successful manual-band donor result is not
evidence that this automatic step already works. Turning-flight fit rejection
must not become a compulsory discovery gate.
