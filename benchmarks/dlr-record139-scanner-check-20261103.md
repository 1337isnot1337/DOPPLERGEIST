# DLR RECORD 139 real-flight scanner check

## Source and scope

- Source: [RECORD 139, Benchmark for Acoustic Source Localization of Flyover Microphone Array Measurements](https://zenodo.org/records/20494053), by DLR researchers.
- The publisher describes one 2016 flyover recording of the DLR ATRA Airbus A320-232, with calibrated pressure signals from a 231-microphone array and an 88 m/s aircraft velocity. The downloaded HDF5 records 48,192 Hz audio and trajectory references in sample-relative local coordinates.
- License: CC BY 4.0, verified from the Zenodo record API metadata. The raw 311,789,336-byte HDF5 and the derived WAV are kept under `/home/cinna/.local/state/dopplergeist-dlr-record139-20261103/`; neither is committed here.
- This was scanner-only. No flight matching, aircraft association or geolocation ran.

## Scanned excerpt

The raw HDF5 member `REC139.h5` has MD5 `1fb08d67965550d26d5b35abaf71f3f3` and SHA-256 `826fb22c2daa5c09ea378f4f1104428ab064c00373cff94fa4fc957822084fa4`. It contains 231 channels by 337,344 samples, or seven seconds. The scanned WAV is channel 80, the microphone nearest the array origin: `[0.125, -0.043, -0.079]` m in the array's local coordinate frame. A single constant gain of `0.3188036516506252` scales the channel peak to 0.95; this does not alter its time or frequency structure. The resulting float WAV SHA-256 is `469c4257f4d230ac02adbc435ebdeae457dfefe4ceae3275a733b0543d4d7ae1`.

The HDF5 includes three trajectory reference groups aligned to sample indices, but the inspected file has no absolute UTC timestamp or geodetic microphone coordinate. This prevents using this recording as a standard location-recovery benchmark without outside source evidence.

## Scanner result

The current-main scanner at commit `4dadf3903551a82d526163157c300b35814e1b5b` returned **no proposals**: zero ridges and zero harmonic groups. The scanner reported 4.278 seconds of runtime. This records a real publisher-identified aircraft excerpt that the current scanner did not detect; it does not establish absence of Doppler structure in other microphones or in the source's full data.

Recreate the WAV from the downloaded HDF5 with `h5py`, NumPy and SciPy:

```python
import h5py
import numpy as np
from scipy.io import wavfile

with h5py.File("REC139.h5", "r") as source:
    positions = source["MetaData/ArrayAttributes/microphonePositionsM"][:]
    channel = int(np.argmin(np.linalg.norm(positions, axis=1)))
    pressure = source["MicrophoneData/microphoneDataPa"]
    sample_rate = int(round(float(pressure.attrs["sampleRateHz"])))
    samples = pressure[channel, :].astype(np.float32)
    samples *= 0.95 / np.max(np.abs(samples))
    wavfile.write("REC139-center-mic.wav", sample_rate, samples)
```

Reproduce the scanner stage after placing that WAV at the state path above:

```bash
PYTHONPATH=src .venv/bin/python scripts/collect_audio_corpus.py scan-one \
  /home/cinna/.local/state/dopplergeist-dlr-record139-20261103/REC139-center-mic.wav \
  --output /home/cinna/.local/state/dopplergeist-dlr-record139-20261103/scan.json
```

The conversion selects the microphone nearest `[0, 0, 0]` in
`/MetaData/ArrayAttributes/microphonePositionsM`, reads that row from
`/MicrophoneData/microphoneDataPa`, and writes the constant-gain-scaled float
samples at the source sample rate. The upstream Zenodo record and its file
checksums identify the source; the converted audio is not included in the repo.
