# DLR RECORD139: independent field-data eligibility inspection

## Finding

The published dataset is useful for a local microphone-array physical comparison,
but the inspected release does **not establish an eligible case for the project's
absolute-location/recording-clock field corpus**. Issue #53 remains open. No audio
conversion, event-discovery run, localization, holdout evaluation or acceptance
decision was performed in this inspection.

The source is Timo Schumacher and Henri Siller (DLR),
[RECORD 139, version 1](https://zenodo.org/records/20494053),
[DOI 10.5281/zenodo.20494053](https://doi.org/10.5281/zenodo.20494053),
licensed **CC BY 4.0** in the publisher's record. The publisher describes a single
2016 A320 flyover. The source files are unmodified; this inventory and eligibility
assessment are derived work. Attribution and original source links are retained.

## What the actual files establish

All three published files were downloaded and matched their declared byte sizes
and MD5 checksums. The 311,789,336-byte HDF5 file also has SHA256
`826fb22c2daa5c09ea378f4f1104428ab064c00373cff94fa4fc957822084fa4`.
The pressure samples were not loaded for an acoustic analysis. Its complete
32-object named metadata hierarchy and attributes were inspected.

| Recorded item | Observed value |
| --- | --- |
| Pressure array | 231 channels × 337,344 samples, float32, named in Pa |
| Sample rate | 48,192 Hz |
| Delivered duration | 337,344 / 48,192 = **7.000 seconds** |
| Microphone positions | 231 × 3 local Cartesian coordinates in metres |
| Microphone x range | −20.958 to 22.438 m |
| Microphone y range | −18.680 to 17.213 m |
| Microphone z range | −0.403 to 0.074 m |
| Sound speed | 339.8900146484375 m/s |
| Trajectory reference samples | 89,926; 152,624; 210,406 |

The trajectory records also provide local reference positions, velocities,
orientation and wind vectors. Dividing the reference sample numbers by the
sample rate gives approximately 1.866, 3.167 and 4.366 seconds. Those are arithmetic
ratios, not absolute UTC or a resolution of zero-versus-one-based sample indexing.
The angle-labelled `Trajectory060`, `Trajectory090` and `Trajectory120` groups are
reference states within this one flyover; they are not three independent events.

No latitude/longitude tie, geodetic coordinate reference, absolute sample-zero UTC,
or measured uncertainty for those ties was found in the inspected metadata.
The small companion files describe aircraft outlines and analysis-region geometry;
they do not supply those missing bindings. Local metre coordinates and sample
numbers cannot simply be relabelled as microphone GPS and a measured UTC clock.
Similarly, 231 channels from one flyover do not establish multiple independently
documented recording sessions, devices and environments or a sealed holdout.

## Preserved evidence and reproducibility

`eligibility.json` records the measured dimensions, local coordinate ranges,
trajectory reference states, the unmet requirements and the explicit unrun status.
`hdf5-metadata.json` retains every inspected object/attribute and small metadata
array, plus the exact reader-source hash. Large pressure arrays are represented by
shape, type and attributes; the 311.8 MB source file remains at its DOI source.
Native publisher metadata, both small companion files and download receipts are
retained with checksums. `manifest.json` hashes this evidence directory and excludes
itself. The native companion files retain their publisher whitespace, including
trailing spaces; they are not reformatted copies.

The executed reader is `inspect_hdf5.py`: h5py **3.16.0**, HDF5 **2.0.0**,
NumPy **2.5.4**, Python **3.12**. Its isolated dependency receipt includes the wheel
digest. It does not follow external/soft HDF5 links. To reproduce, copy the reader
and download receipt into a fresh output directory, restore the publisher's exact
`REC139.h5` there, verify its checksum, install the pinned reader into that
directory's `reader-deps/`, and execute the copied script. Preserve this completed
inspection and use a new directory for any later acoustic experiment.

This finding narrows one public-data lead. It neither invalidates the dataset's
intended beamforming use nor supplies the missing independent real-recording
validation for DOPPLERGEIST.
