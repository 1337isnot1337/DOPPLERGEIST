#!/usr/bin/env python3
"""Drive the actual bundled upload form; no request interception or fake data."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import re
import sys

from playwright.sync_api import sync_playwright


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=630)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    request = json.loads(args.request.read_text())
    if set(request) - {"schema_version", "search", "time_window"}:
        raise ValueError("Unexpected upload fields")
    if request.get("search", {}) != {"coverage": "conus"}:
        raise ValueError("Browser acceptance must not supply a truth-derived search box")
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, timezone_id="UTC")
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(args.base_url, wait_until="networkidle")
            page.locator("#audio").set_input_files(str(args.audio.resolve()))
            for selector, field in (("#start", "start_utc"), ("#end", "end_utc")):
                if request.get("time_window"):
                    moment = datetime.fromisoformat(request["time_window"][field].replace("Z", "+00:00")).astimezone(timezone.utc)
                    if moment.microsecond:
                        raise ValueError("The current browser time fields accept whole seconds only")
                    # datetime-local normalizes trailing zero seconds away.
                    # Supply that canonical value to the real form control.
                    pattern = "%Y-%m-%dT%H:%M:%S" if moment.second else "%Y-%m-%dT%H:%M"
                    page.locator(selector).fill(moment.strftime(pattern))
            if request.get("time_window", {}).get("source_detail"):
                page.locator("#time-source").fill(request["time_window"]["source_detail"])
            with page.expect_response(lambda response: response.url.endswith("/api/jobs")
                                      and response.request.method == "POST") as pending:
                page.locator("#submit").click()
            response = pending.value
            if response.status != 202:
                raise RuntimeError(f"Browser upload failed: HTTP {response.status} {response.text()}")
            # History.replaceState in the application can evict Chromium's
            # inspector response-body cache. The page consumed that response;
            # read its displayed job ID and verify it through the real job API.
            page.wait_for_function("() => /^JOB [0-9a-f]{32}$/.test(document.querySelector('#job-id').textContent)")
            job_id = re.fullmatch(r"JOB ([0-9a-f]{32})", page.locator("#job-id").inner_text()).group(1)
            queued = {"job_id": job_id, "upload_http_status": response.status,
                      "job_id_source": "actual upload-form display"}
            write_json(output / "submission.json", queued)
            write_json(output / "browser-upload-headers.json", {
                k: v for k, v in response.request.all_headers().items()
                if k in {"content-type", "content-length", "x-filename", "x-dopplergeist-request"}
            })
            page.wait_for_function("""() => ['needs input', 'succeeded', 'inconclusive', 'failed', 'cancelled']
                .includes(document.querySelector('#status').textContent)""", timeout=args.timeout * 1000)
            canonical = context.request.get(f"{args.base_url}/api/jobs/{queued['job_id']}")
            if not canonical.ok:
                raise RuntimeError("Cannot read the browser-submitted job")
            value = canonical.json()
            write_json(output / "result.json", value)
            expected_display = value["status"].replace("_", " ")
            if page.locator("#status").text_content() != expected_display:
                raise RuntimeError("UI status disagrees with the job API")
            # Reload tests the actual saved-job URL, rather than an in-memory render.
            page.reload(wait_until="networkidle")
            page.wait_for_function("expected => document.querySelector('#status').textContent === expected",
                                   arg=expected_display, timeout=15000)
            if queued["job_id"] not in page.locator("#job-id").inner_text():
                raise RuntimeError("Reload restored a different job")
            page.locator("#downloads").evaluate("element => element.open = true")
            page.wait_for_function("() => document.querySelector('#artifacts').children.length > 0", timeout=15000)
            if errors:
                raise RuntimeError(f"Browser JavaScript errors: {errors}")
            page.set_viewport_size({"width": 390, "height": 844})
            mobile = page.evaluate("({viewport_width: innerWidth, document_width: document.documentElement.scrollWidth})")
            page.screenshot(path=str(output / "page-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1100})
            if mobile["document_width"] > mobile["viewport_width"]:
                raise RuntimeError("Mobile result page overflows horizontally")
            write_json(output / "browser.json", {"browser": browser.version, "url": page.url,
                       "python": sys.version, "playwright": importlib.metadata.version("playwright"),
                       "status": value["status"], "javascript_errors": errors,
                       "reloaded_job_verified": True, "mobile_layout": mobile})
        finally:
            (output / "page.txt").write_text(page.locator("body").inner_text())
            page.screenshot(path=str(output / "page.png"), full_page=True)
            context.tracing.stop(path=str(output / "trace.zip"))
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
