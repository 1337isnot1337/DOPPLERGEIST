# Worker 4 measured integration and public-camera checks

The JSON reports preserve every run in this lane, including work limits, missing
recording clocks and invalid trailing segments. No case below is an independently
validated real national localization success.

- `automatic-synthetic-report.json`: three actual normal-input CLI experiments.
  The finer-grid run wrote all 19,278 tiles but exhausted its 600-second budget
  during refinement. The two 5 km coarse / 1 km grid-refinement runs completed all
  3,116 CONUS tiles. Both found the correct flight pair and a best diagnostic
  candidate 5.5693 m from independently joined synthetic truth. One replay used
  fully opaque IDs. Both final decisions were `inconclusive /
  alternatives_not_assessed`; a local altitude-only sensitivity radius was also
  109.74 m under the original 100 m policy. The bounded retained alternatives were
  not exhaustive. These candidates are not counted as accepted locations.
- `public-webcam-report.json`: six actual HTTP uploads. The three original usable
  clips and corrected Herald Square clip returned `needs_input /
  recording_time_required`, with zero proposals. Two invalid encoder tails
  returned `failed / invalid_media`. Input bytes, polling results and artifact
  readback were verified for every case. Zero proposals are observed outcomes,
  not certified aircraft-negative ground truth.
- `receipt.json`: source/input/configuration hashes, completed scope, independent
  regression checks and reported matching-worker regressions. HTTP process memory
  was not measured and remains absent. The matching-worker two-event and faint
  regional errors regressed to 116.16 m and 537.57 m; their clocks/reference labels
  remain limited, and the 606.954 m sensitivity profile reaches a boundary. A
  relaxed error target does not make that truncated profile complete.

The original public-camera audio-only capture collapsed part of the A/V timeline:
the 150-second Times Square segments contain about 147.9/148.5 seconds. All media
and invalid tails are preserved. The corrected Herald capture uses the separate
capture worker's timestamp-preserving script at `654fecc`; no video is saved. It
contains exactly 150.0 decoded seconds, SHA256
`ae0856bb4ec6187bc1b84eef992a9d10e73b276cf2de8d9f4cd36ba1f4ea98d0`,
received over 134.85 wall seconds because the stream is buffered.

Both EarthCam sources publish site markers and advertise audio. Neither inspected
HLS playlist supplies a programme date/time and inspected source frames have no
encoded recording clock. Receipt UTC is not microphone sample-zero UTC; the
map-marker microphone uncertainty is also unestablished. These remain real audio
discovery/product cases, explicitly ineligible for location-error claims. Source
media, stream queries, local decoder logs, credentials and caches are not committed.

Historical results and policy versions are unchanged. The current evaluator shows
100/500/1,000 m tiers, separates diagnostic errors from accepted fixes and reports
all statuses. No result was promoted by changing its original threshold.
