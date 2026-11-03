# Real-recording browser checks

These optional helpers exercise the actual local application using a supplied
real recording or a preserved real-recording job. They do not create test audio
or replace any scientific stage. Install Playwright and its headless Chromium
runtime in the environment used to run the helpers.

Start the installed service with `dopplergeist serve --jobs path/to/jobs`.
Then use a new output directory:

```bash
python scripts/verify_upload_browser.py --base-url http://127.0.0.1:8765 \
  --audio path/to/real-recording.mp3 --request request.json --output results/new-upload-check
```

`request.json` supplies only the normal request fields, for example
`{"schema_version":1,"search":{"coverage":"conus"}}`. Supply a defensible
recording-start window when available. The helper uses the real upload form and
checks the terminal result, original download, reload and mobile layout.

To check a preserved terminal job through an installed environment:

```bash
python scripts/verify_result_browser.py --python path/to/installed/python \
  --fixture path/to/jobs/JOB_ID --output results/new-readback-check
```

The second command copies the job, serves it through the real API and checks
artifact/readback consistency and candidate display. It does not rerun analysis.
Both helpers launch headless browsers and do not operate the host desktop.

Transport/UI checks do not establish location accuracy. Missing recorder time,
location truth or flight coverage must remain explicit in the scientific result.
Use actual recordings only; the earlier generated-codec/control campaigns remain
historical and are not part of these helpers.
