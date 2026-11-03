# Inspected NASA 2016 small-UAS flyover release

This is a source-eligibility inspection for #53, not a localization result or a
replacement for its sealed multi-device/environment field corpus. It concerns
the older public flyover archive, separate from the 2026 Moog hover release.

Primary sources are the [NASA data description](https://data.nasa.gov/docs/datasets/rfk401li/Data_Description_20160203.pdf),
the [release catalog](https://catalog.data.gov/dataset/small-uas-flyover-acoustics-data)
and the [2018 instrumentation overview](https://ntrs.nasa.gov/api/citations/20180002208/downloads/20180002208.pdf).
The memo describes microphone GPS positions, per-sample acoustic UTC seconds
past midnight and vehicle GPS/RTK time arrays. AP Hill microphone positions were
surveyed; Virginia Beach positions used averaged GPS and its vertical heights
were not accurately measured. The overview describes a GPS time-code signal
acquired simultaneously with acoustic data. These are documented acquisition
facts, not a measured clock-uncertainty bound supplied by this inspection.

The inspected archive is 1,693,926,297 bytes with 67 entries: 62 MAT files and five
companions. All five companions plus the first lexical Cub and Edge MAT members
were inspected, a selection declared before acoustic or trajectory inspection.
Every selected member passed central-directory length/CRC checks; complete
member SHA256 and HTTP-range receipts are preserved. The bounded reader avoids
downloading the entire archive. Raw source files stay local or at NASA.

| Member | Delivered samples/channels | Acoustic UTC-of-day span | Quality finding |
| --- | --- | --- | --- |
| `cub_flyover_107.mat` | 1,964,032 × 4 | 62795.07585–62893.27648617569 s | Every one of 973 delivered RTK-status values is zero; the source defines zero as poor. GPS fallback exists; centimeter RTK precision cannot be assumed. |
| `edge_flyover_038.mat` | 1,188,188 × 4 | 52311.79065000248–52371.19999856391 s | Delivered file has no RTK-status field. Virginia Beach height uncertainty remains explicit. |

The memo documents a Piksi duplicate-position firmware bug whose effect on
position accuracy is unknown. It also says poor-acoustic events were removed
before publication. The workbook and archive do not fully agree: the archive
contains Cub 110 and Edge 41 without workbook entries, while workbook Cub 109
has no archive member. This is preserved, not silently repaired. Cub 107 is
labelled a descending, low-power pass; the mechanical file selection was kept.

Eligibility remains unproven. The inspected MAT structures and workbook supply
UTC **time of day**, not an absolute recording date or measured sample-zero clock
uncertainty. Their January 2016 MAT creation headers are processing timestamps,
not recording clocks. The memo gives December 2014 / August 2015 campaign months;
these are defensible broad date windows, not exact timestamps. Microphone
geodetic uncertainty and vertical datum still need reconciliation. Relative NED
flight coordinates require a documented georeferencing preparation step; target
coordinates must not enter a localization request, seed or search bound.

The release also lacks complete nationwide historical traffic, including noted
incidental background aircraft, and the required sealed holdout/corpus design.
It is a promising independent physical source; it cannot close #53 or #13 on
the current evidence. No waveform conversion, event discovery, localization,
author outreach or acceptance decision was performed by this inspection.

Reproduction:

```bash
.venv/bin/python scripts/inspect_nasa_flyover_release.py \
  --output results/new-nasa-inspection --first-fixed-wing
```

Use a new output directory. `--source-cache` optionally reuses existing members
only after their length and CRC match the freshly fetched public directory.
Two initial network failures remain preserved separately. The completed third
inspection reused verified prior members and fetched the missing Edge member;
it is not a claim that every initial download succeeded. Native metadata,
tool hashes and eligibility findings are in `evidence/w1-nasa-eligibility-20261103`.
