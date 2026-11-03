# Six-event automatic pipeline replay

This lane consumes the primary's frozen six-flyover development fixture from
release `multi-event-fixtures-2026-11-03`, generator `1f03425`. It does not generate
another input or claim a sealed independent real-world holdout.

The source archive SHA256 is
`a6d79edca1407324ad77fee6b97812eb11f7a84cdb2308d12bd8f2663d4b396c`.
Only its six `inputs/` files were extracted. Every input matches the release's
per-file manifest. The 1,400 s MP3 SHA256 is
`1ab55fb23eb2dff907ef48d81e3dabb33524b34af12c58e714b96212b9f69aee`.
The supplied Parquet contains all 18 opaque trajectories in the finite synthetic
population. No aircraft type is removed. The separate truth/renderer files and
generation metadata are not mounted in the backend.

The integrated code is `39634c3fc565a3d025a661f90eddae54430591f9`: main plus published
product and all-event driver changes. Both independent tiled-search test additions
were retained when resolving their merge conflict. The initial collection failure
from unresolved conflict markers is preserved separately. The corrected complete
integration passes 196 tests. No producer implementation was changed in this lane.

The installed wheel SHA256 is
`62d310e01d4a4e26317ad11b686e604bb79551c934efc73b02f6fc89bf1c28a8`.
All 23 installed runtime source/static files match the frozen checkout snapshot.
Python 3.12.3 and the existing isolated scientific dependencies are used. The
backend runs in a filesystem/network namespace containing only system runtime,
installed package/dependencies, read-only inputs and writable outputs. Home,
GitHub authentication, full checkout, generator, renderer and truth are absent.
This isolates the executing backend; the public development generator is known
to the experimenter, so experimenter blinding is not claimed.

The derived v2 index has 4,878 rows and 18 complete segments. It was built inside
the same input-only namespace in 0.423 s, with source paths under `/inputs`.
Its SHA256 is
`3a7eea21f81c8822b203817bb3796b71f56d2e77e8d21c49c5de66000ebe0318`.

The normal request supplies only the original MP3, CONUS coverage and the explicit
synthetic clock from `inputs/request.json`. Operator configuration uses the full
provided flight index, terrain and zero synthetic geoid. It keeps the 2 km coarse
and 100 m refinement grids and all-event association defaults. Eight-cell tiles
bound per-tile work on this host; no `max_events`, truth-derived bounds, selected
IDs, manual windows/bands or true location are supplied. The job wall budget is
3,600 s. Any exhausted work or incomplete search remains explicit.

The run invokes the actual installed CLI and persistent job process. Capture every
stage, all detected/matched/unmatched events, competing hypotheses, runtime/RSS,
input/code hashes, failure or inconclusive reason, and the complete final result.
Only after the job is terminal may the separate truth file be opened to report
association and position errors at 100/500/1,000 m. Check that later flyovers enter
the joint score/refinement; a narrow finalist contribution check may reuse the
frozen search rather than duplicate the national sweep.

Before the terminal result, the score-participation check is fixed as follows:
take the leading search row and, if different, the first retained row matching
all proposed groups. Recompute its score at the reported location and shared
clock, then at four projected offsets of 100 m east/west/north/south. Keep the
clock and flight assignment fixed and reuse only the normal bounded per-event
source fits. Save every event's residual and normalized support contribution.
This checks whether later groups enter the score and respond to geometry; it is
not leave-one-flyover-out prediction, a new global search or a confidence claim.

The first namespace launch terminated before decoding: FFprobe could not resolve
`libblas.so.3`, whose system symlink traverses `/etc/alternatives`. Its failed job
and direct diagnostic are preserved. Mounting that system symlink directory read
only makes FFprobe and FFmpeg preflights pass. A second run uses a new output
directory with the identical installed wheel, input bytes and work policy. The
environment repair supplies no data or scientific hint to the backend.

At the source freeze, finite-search decision semantics are still under producer
review. A correct close hypothesis is not automatically an accepted result, and
this run cannot establish independent national real-audio performance. Preserve
all outcomes without changing the input, detector or acceptance gates to obtain
a preferred result.
