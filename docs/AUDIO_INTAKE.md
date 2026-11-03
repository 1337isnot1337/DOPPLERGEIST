# Whole-recording audio intake

`intake.intake_recording(source, output_dir, time_window=None, sample_rate_hz=4000)`
returns an `IntakeRecording` with `samples_path`, shared-contract `metadata`, and
intake-specific `diagnostics`. The output directory must not already contain
intake artifacts. It writes mono little-endian float32 `recording.f32`, validated
`recording.json`, and `intake.json` with probe time hints and the exact decode
command. Source files are read, never modified. The source SHA256 is calculated
in blocks and source stat identity is checked across decoding.

ffprobe selects the first actual audio stream regardless of extension. ffmpeg
averages all channels explicitly before resampling and applies its codec skip /
discard handling. Time zero is the first decoded sample, not a container PTS.
Decoded duration comes from sample count / sample rate. `iter_chunks(chunk_s,
overlap_s)` returns `(audio_relative_start_s, float32_samples)` from a disk-backed
cache, bounding working memory independently of recording length. Acoustic
analysis is available before the recording UTC clock is known.

Chunk iteration seeks and reads only the active float32 window. It does not map
the entire cache into the process: touched memory-map pages otherwise caused
resident memory to grow with recording length. With fixed 120 s / 60 s chunks,
synthetic 32 MiB and 128 MiB raw caches formerly added 35.58 MiB / 131.73 MiB
peak RSS; explicit window reads add 3.63 MiB / 3.67 MiB. These are Linux iterator
stress checks, not media acquisitions or full-pipeline resource measurements.
Consumer event/result storage and plotting have separate memory costs.

The shared `time_window` bounds the UTC time of sample zero, including recording
clock uncertainty and any known trimming. Pass an explicit defensible user
window or externally verified recording metadata via that contract. Ordinary
MP3/WAV creation, edit, date, upload and filesystem times cannot establish the
recording clock. Embedded date/time tags are retained as **untrusted hints** in
`intake.json`; without an explicit window `recording.time_status == 'needs_input'`.
This implementation deliberately does not promote an unverified tag to a clock.

`AudioIntakeError.code` distinguishes unreadable_audio, invalid_media,
no_audio_stream, decoder_unavailable, decode_failed, invalid_samples, empty_audio
and source_changed. Existing output raises FileExistsError. Input parameter and
shared-contract validation raise ValueError. ffmpeg and ffprobe must be on PATH.

decoder_unavailable also covers executable launch errors and POSIX startup
statuses126/127, including unavailable runtime dependencies. A valid recording
must not be labelled corrupt merely because the decoder cannot start. Ordinary
probe rejection remains invalid_media; a decoder that starts but rejects the
audio remains decode_failed. Private executable-stub tests cover these paths
without changing installed binaries, preserve input bytes and leave no finalized
cache on failure. Historical namespace failures retain their original outcomes.

Verification: `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_intake.py`.
The tests encode a real MP3 with libmp3lame, compare WAV/MP3 burst timings at three
positions to <=1 ms and duration to one 4000 Hz sample, check 48 kHz stereo channel
averaging/resampling, overlapping chunk offsets, a 50 ms clip, missing/ambiguous
UTC, malformed/missing/empty media, hash identity and refusal to overwrite output.
These tolerances establish behavior for the exercised codec/container versions;
unknown encoders that omit gapless metadata can retain unknown leading padding.
The Linux RSS regression reads a synthetic 128 MiB cache with a 32 MiB growth
budget and verifies end coverage/checksum. Exact canonical six-event detection
JSON also matches the earlier frozen run after the I/O change.
