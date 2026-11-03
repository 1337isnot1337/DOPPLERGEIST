# Independent all-event integration check

The combined repository suite and four independent decision safeguards passed: **205 tests, zero failures and zero skips** in 48.27 seconds. The test process permitted loopback sockets, so HTTP service checks ran. The native JUnit, log and invocation receipt are preserved here.

The executed local source was `e6a78249c8bd29bc552e3da4d2803fa6b28565fa`. Its complete Git tree, `1b2dcbbe0e39de1053b0ccec60b543fc19560274`, is published unchanged at [455bb4c](https://github.com/1337isnot1337/DOPPLERGEIST/commit/455bb4ca3d3e92360b9cf695bbc2376df576f8a1). The published commit records the combined source; it does not claim to be the local commit that executed. `source.json` identifies every component.

This source includes the bounded all-event matcher and search driver, the 1,000 m decision policy, and the authoritative full-profile repair from #52. It still awaits the product adapter for score normalization, original clock bounds and unmatched proposal identifiers. The finite-search alternatives flag remains false. These tests establish integration behavior, not an accepted automatic location.

## Canonical input restoration

The [primary fixture release](https://github.com/1337isnot1337/DOPPLERGEIST/releases/tag/multi-event-fixtures-2026-11-03) supplies the four-event case. All nine extracted file digests match its manifest. The MP3 SHA-256 is `6c44970b812d9147146c2f712c5012efd255ce80bb240aa6c1d9f3a796c45e85`. The canonical tracks contain all twelve opaque flight segments. No search input contains manual event windows, frequency bands, selected flight identities or receiver coordinates.

The index was prepared before the release download from a local rendering whose Parquet bytes exactly match the canonical release. The local MP3 encoder variant was not used for the recorded canonical smoke. `preparation-receipt.json` retains that earlier preparation revision and index digest. The configured budget was declared before product execution: a 2 km outer grid, 100 m refinement grid, 20 finalists, 200 retained rows and a 2 km profile box. Budget exhaustion or a boundary optimum must remain a limitation.

Truth files were hashed for archive integrity. Their labels were not opened for search preparation and were not mounted in the isolated runtime.

## Installed-package and input-isolation check

The source was archived with only `pyproject.toml` and `src`, then built using the already installed base-runtime setuptools backend. No dependency installation or network access was used by the build. The wheel SHA-256 is `e5abb62c66911ad293b52799d3b7e9aa7069194812a611df1965e19d84d3737d`. Its extracted file manifest is preserved.

The namespace smoke passed in 0.858 seconds. Product imports resolved to `/app`, dependencies to `/deps`, and child-process imports used the same installed package. The smoke read the 3,252-row canonical Parquet and terrain, probed the 960-second canonical MP3, checked the CLI, and verified that source checkout, renderer, generator, truth, host home and host proc paths were absent. It submitted **zero analysis jobs**. This is benchmark input isolation; the shared network namespace permits an external loopback HTTP client. It is not a claim of network isolation or protection against adversarial code.

The runtime wrapper and receipts retain exact local paths. To reuse them on another machine, build the chosen final wheel, extract it with `runtime/prepare_app.py`, and change the absolute interpreter, dependency, app, fixture and prepared-input paths in a new configuration. Keep the old receipt unchanged. The actual browser/HTTP verifier owns the canonical four-event upload, so this worker did not repeat its national search. The six-event CLI lane belongs to the replay verifier.

The first earlier setup build failed because the project environment lacked setuptools. Its failure receipt is retained. The successful build used the installed base runtime, without installing another dependency.

All prior real replays and automatic two-event runs retain their original reports and thresholds. No result in this checkpoint closes the independent field-data requirement in #53.
