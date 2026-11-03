# Frozen actual API ambiguity result

Job `4ca3dab06e3a4f9d9ed7e43c8f278900` was produced by a real HTTP upload of the
full 1180-second synthetic MP3 through intake, automatic discovery, indexed CONUS
search, physical refinement and the confidence producer. It returned
`inconclusive / ambiguous_flight_match`. No coordinates or result were mocked.
The finite simulation has exactly the seven supplied tracks; global source scope
is a closed-world simulation declaration, not a claim about real ADS-B capture.

These files are the unchanged terminal job JSON and selected diagnostic artifacts
from that actual run. They support browser/API **readback** verification without
rerunning science. The original MP3, f32 sample cache, SQLite index, per-tile caches
and environment are excluded. Exact original upload/download SHA256 equality is
recorded in [the receipt](../api-ambiguity-receipt.json).

For a review, copy this directory to a new disposable job root, start the real
service with `--jobs` pointing at that copy, then open
`http://127.0.0.1:8765/?job=4ca3dab06e3a4f9d9ed7e43c8f278900`.
The service reads terminal jobs without replaying them. The result has 106 ranked
hypotheses; the UI shows the first five and an expandable section for the rest.
This render is a frozen real backend result, not a new upload/localization test.

The analysis implementation is pinned by all source hashes in `provenance.json`
and matches commit `1863d8976a06a458ee7c25532c612a8250676574`. Its older common-height
sensitivity scenarios do not establish independent per-flight altitude-datum
uncertainty or calibrated confidence. The original decision is retained unchanged.
