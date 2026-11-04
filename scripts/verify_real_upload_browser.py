#!/usr/bin/env python3
"""Verify a real browser upload or readback of an existing completed real job.

Requires an installed dopplergeist package, Playwright, and its Chromium browser.
Playwright is an optional verification dependency, not a production dependency.
The default expects a real recording without a trustworthy embedded clock.
Use --expect-status/--expect-reason for other actual backend outcomes. A saved
job is copied before readback; it is never resumed or presented as a fresh run.
No synthetic audio or mocked outcomes are used.
A passing browser check does not establish location accuracy.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stop_service(process):
    """Signal only the process group created by this verifier."""
    sent = []
    for signum, grace in ((signal.SIGINT, 10), (signal.SIGTERM, 3), (signal.SIGKILL, 3)):
        if process.poll() is not None:
            break
        try:
            os.killpg(process.pid, signum)
            sent.append(signal.Signals(signum).name)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            continue
    return {"returncode": process.poll(), "signals": sent,
            "clean": process.poll() == 0 and not any(s != "SIGINT" for s in sent)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", nargs="?", type=Path, help="Existing real MP3 recording")
    parser.add_argument("--saved-job", type=Path, help="Copy and inspect a completed real job instead of uploading")
    parser.add_argument("--request", type=Path, help="Existing request JSON; fill its UTC window and bounds through the UI")
    parser.add_argument("--source", type=Path, help="Source directory containing dopplergeist; default checks the installed package")
    parser.add_argument("--browser-executable", type=Path, help="Use an existing Chromium executable")
    parser.add_argument("--expect-status", choices=("needs_input", "failed", "inconclusive", "succeeded", "cancelled"), default="needs_input")
    parser.add_argument("--expect-reason", default="recording_time_required", help="Expected actual reason code; an empty string expects none")
    parser.add_argument("--output", required=True, type=Path, help="New directory; existing paths are refused")
    parser.add_argument("--timeout", type=float, default=900, help="Overall verification budget in seconds")
    args = parser.parse_args()
    if (args.audio is None) == (args.saved_job is None):
        parser.error("Supply exactly one MP3 or --saved-job")
    if args.saved_job is not None and args.request is not None:
        parser.error("A saved job keeps its original request")
    saved_job = args.saved_job.resolve() if args.saved_job else None
    audio = (saved_job / "input.mp3") if saved_job else args.audio.resolve()
    output = args.output.resolve()
    if os.name != "posix":
        parser.error("This verifier requires POSIX process groups (for example, Ubuntu CI)")
    if not audio.is_file() or audio.suffix.lower() != ".mp3" or audio.stat().st_size == 0:
        parser.error("Supply a nonempty existing MP3 file")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    if args.source is not None:
        args.source = args.source.resolve()
        if not (args.source / "dopplergeist" / "service.py").is_file():
            parser.error("--source must contain dopplergeist/service.py")
    wire = json.loads(args.request.read_text()) if args.request else None
    if wire is not None and (not isinstance(wire, dict) or wire.get("schema_version") != 1
                             or set(wire) - {"schema_version", "search", "time_window"}
                             or not isinstance(wire.get("time_window") or {}, dict)
                             or not isinstance(wire.get("search") or {}, dict)
                             or (wire.get("time_window") or {}).get("source", "user") != "user"
                             or (wire.get("search") or {}).get("coverage", "conus") != "conus"):
        parser.error("--request must use the UI's version-one user-time/CONUS contract")
    output.mkdir(parents=True, exist_ok=False)
    jobs = output / "jobs"
    started = time.monotonic()
    deadline = started + args.timeout
    errors, screenshots = [], []
    summary = {"scope": "actual_browser_saved_job" if saved_job else "actual_browser_real_upload", "passed": False,
               "started_utc": datetime.now(timezone.utc).isoformat(),
               "audio": str(audio), "source_sha256": digest(audio),
               "page_errors": errors, "screenshots": screenshots,
               "location_accuracy_evaluated": False}
    if args.source is not None:
        summary["source_directory"] = str(args.source)
        summary["implementation_sha256"] = {name: digest(args.source / "dopplergeist" / name)
                                            for name in ("service.py", "jobs.py", "automatic.py", "web/app.js")}
    process = log = None
    final = job_directory = None
    old_handlers = {}

    def milliseconds(cap=None):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("Browser verification exceeded its time budget")
        return max(1, int(1000 * (min(left, cap) if cap else left)))

    def interrupted(signum, _frame):
        raise InterruptedError(f"Interrupted by {signal.Signals(signum).name}")

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            old_handlers[signum] = signal.signal(signum, interrupted)
        # Lazy import keeps --help usable without the optional browser dependency.
        from playwright.sync_api import expect, sync_playwright
        if saved_job is not None:
            require(re.fullmatch(r"[0-9a-f]{32}", saved_job.name), "Saved directory must have its real job ID")
            saved_result = json.loads((saved_job / "result.json").read_text())
            require(saved_result.get("job_id") == saved_job.name
                    and saved_result.get("status") in {"needs_input", "failed", "inconclusive", "succeeded", "cancelled"},
                    "Only completed real jobs can be inspected")
            shutil.copytree(saved_job, jobs / saved_job.name)
            summary["saved_result_sha256"] = digest(saved_job / "result.json")
        command = [sys.executable, *([] if args.source else ["-I"]), "-m", "dopplergeist.cli", "serve",
                   "--port", "0", "--jobs", str(jobs), "--max-runtime", str(args.timeout)]
        summary["service_command"] = command
        log_path = output / "service.log"
        log = log_path.open("xb")
        environment = dict(os.environ, PYTHONPATH=str(args.source)) if args.source else None
        process = subprocess.Popen(command, cwd=output, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        startup_deadline = min(deadline, time.monotonic() + 30)
        while True:
            require(process.poll() is None, "Service exited during startup; inspect service.log")
            match = re.search(r"DOPPLERGEIST: (http://127\.0\.0\.1:\d+) ", log_path.read_text())
            if match:
                origin = match.group(1)
                break
            if time.monotonic() >= startup_deadline:
                raise TimeoutError("Service did not start within the startup budget")
            time.sleep(0.1)

        with sync_playwright() as playwright:
            browser = page = None
            try:
                launch = {"headless": True, "timeout": milliseconds(30)}
                if args.browser_executable is not None:
                    launch["executable_path"] = str(args.browser_executable.resolve())
                browser = playwright.chromium.launch(**launch)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                context.set_default_timeout(milliseconds(30))
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(origin, wait_until="domcontentloaded", timeout=milliseconds(30))
                for selector in ("#start", "#end", "#time-source"):
                    expect(page.locator(selector)).to_have_value("", timeout=milliseconds(10))
                if saved_job is not None:
                    job_id = saved_job.name
                    page.goto(origin + "/?job=" + job_id, wait_until="domcontentloaded", timeout=milliseconds(30))
                else:
                    if wire is not None:
                        window = wire.get("time_window")
                        if window:
                            for selector, key in (("#start", "start_utc"), ("#end", "end_utc")):
                                stamp = datetime.fromisoformat(window[key].replace("Z", "+00:00"))
                                require(stamp.tzinfo is not None, "Request timestamps must include a timezone")
                                value = stamp.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
                                page.locator(selector).fill(value)
                            page.locator("#time-source").fill(window.get("source_detail", ""))
                        bounds = (wire.get("search") or {}).get("bounds_wsen")
                        if bounds is not None:
                            require(len(bounds) == 4, "Expected four search bounds")
                            for selector, value in zip(("#bbox-w", "#bbox-s", "#bbox-e", "#bbox-n"), bounds):
                                page.locator(selector).fill(str(value))
                    page.locator("#audio").set_input_files(str(audio), timeout=milliseconds(30))
                    with page.expect_response(lambda response: response.url == origin + "/api/jobs"
                                              and response.request.method == "POST",
                                              timeout=milliseconds()) as uploaded:
                        page.locator("#submit").click(timeout=milliseconds(30))
                    response = uploaded.value
                    require(response.status == 202, f"UI upload returned HTTP {response.status}")
                    summary["submitted_request"] = json.loads(response.request.headers["x-dopplergeist-request"])
                    # Large uploads can evict response bodies from Chrome's inspector cache.
                    # Read the rendered identifier, then fetch results directly.
                    job_label = page.locator("#job-id")
                    expect(job_label).to_have_text(re.compile(r"^JOB [0-9a-f]{32}$"), timeout=milliseconds(30))
                    job_id = job_label.inner_text(timeout=milliseconds(10)).strip().removeprefix("JOB ")
                require(re.fullmatch(r"[0-9a-f]{32}", job_id), "Invalid submitted job identifier")
                job_directory = jobs / job_id
                saved_url = origin + "/?job=" + job_id
                summary.update(job_id=job_id, saved_job_url=saved_url)
                page.wait_for_url(saved_url, timeout=milliseconds(30))
                terminal = re.compile(r"^(needs input|succeeded|inconclusive|failed|cancelled)$")
                expect(page.locator("#status")).to_have_text(terminal, timeout=milliseconds())

                def api_result():
                    reply = context.request.get(origin + "/api/jobs/" + job_id, timeout=milliseconds(30))
                    require(reply.status == 200, f"Job API returned HTTP {reply.status}")
                    return reply.json()

                final = api_result()
                summary.update(status=final.get("status"), reason_code=final.get("reason_code"),
                               event_count=len(final.get("events", [])))
                require(final.get("job_id") == job_id, "API returned a different job")
                require(final.get("status") == args.expect_status, f"Expected {args.expect_status}")
                require(final.get("reason_code") == (args.expect_reason or None), f"Expected reason {args.expect_reason!r}")
                if saved_job is not None:
                    require(final == saved_result, "Saved backend result changed during readback")
                if args.expect_reason == "recording_time_required":
                    require("time_window" in final.get("required_fields", []), "API omitted required time_window")
                    require(not final.get("candidates"), "Undated result contains location candidates")

                def check_display():
                    expect(page.locator("#status")).to_have_text(args.expect_status.replace("_", " "), timeout=milliseconds(30))
                    expect(page.locator("#job-id")).to_have_text("JOB " + job_id, timeout=milliseconds(10))
                    expect(page.locator("#events .event")).to_have_count(len(final.get("events", [])), timeout=milliseconds(30))
                    expect(page.locator("#message")).to_have_text(final["message"], timeout=milliseconds(10))
                    required = final.get("required_fields", [])
                    if required:
                        expect(page.locator("#required")).to_be_visible(timeout=milliseconds(10))
                        for name in required:
                            expect(page.locator("#required")).to_contain_text(name, timeout=milliseconds(10))
                    else:
                        expect(page.locator("#required")).to_be_hidden(timeout=milliseconds(10))
                    candidates = final.get("candidates", [])
                    expect(page.locator("#candidates .candidate")).to_have_count(len(candidates), timeout=milliseconds(10))
                    additional = page.locator("#candidates details")
                    if additional.count() and additional.get_attribute("open") is None:
                        additional.locator("summary").click(timeout=milliseconds(10))
                    for i, candidate in enumerate(candidates):
                        card = page.locator("#candidates .candidate").nth(i)
                        expect(card).to_be_visible(timeout=milliseconds(10))
                        expect(card).to_contain_text(f"{candidate['lat']:.6f}, {candidate['lon']:.6f}", timeout=milliseconds(10))
                        expect(card).to_contain_text("not a probability", timeout=milliseconds(10))
                    if candidates and args.expect_status != "succeeded":
                        expect(page.locator("#candidates h3")).to_contain_text("result remains inconclusive")
                    expect(page.locator("#upload-error")).to_have_text("", timeout=milliseconds(10))
                    expect(page.locator("#connection")).to_have_text("", timeout=milliseconds(10))

                check_display()
                summary["displayed_event_count"] = page.locator("#events .event").count()
                summary["displayed_candidate_count"] = page.locator("#candidates .candidate").count()
                summary["required_message"] = page.locator("#required").inner_text()
                page.locator("#status").scroll_into_view_if_needed(timeout=milliseconds(10))
                page.screenshot(path=str(output / "result.png"), timeout=milliseconds(10))
                screenshots.append("result.png")
                if final.get("candidates"):
                    page.locator("#candidates").screenshot(path=str(output / "candidates.png"), timeout=milliseconds(10))
                    screenshots.append("candidates.png")
                original_link = page.locator('#artifacts a').filter(has_text=re.compile(r"^input\.mp3$"))
                expect(original_link).to_have_count(1, timeout=milliseconds(30))
                page.locator("#downloads > summary").click(timeout=milliseconds(10))
                expect(original_link).to_be_visible(timeout=milliseconds(10))
                with page.expect_download(timeout=milliseconds(30)) as downloaded:
                    original_link.click(timeout=milliseconds(30))
                download_path = output / "downloaded-original.mp3"
                downloaded.value.save_as(download_path)
                require(digest(download_path) == summary["source_sha256"], "Browser artifact download changed original bytes")
                summary["artifact_download_verified"] = True
                figures = page.locator("#diagnostics figure.diagnostic")
                if figures.count():
                    figure = figures.first
                    figure.scroll_into_view_if_needed(timeout=milliseconds(10))
                    page.wait_for_function("""() => {
                        const image = document.querySelector('#diagnostics figure.diagnostic img');
                        return image && image.complete && image.naturalWidth > 0 && image.naturalHeight > 0;
                    }""", timeout=milliseconds(30))
                    image = figure.locator("img").evaluate("image => ({src: image.getAttribute('src'), width: image.naturalWidth, height: image.naturalHeight})")
                    require(image["src"].startswith(f"/api/jobs/{job_id}/artifacts/"), "Evidence image belongs to a different job")
                    summary["loaded_evidence_image"] = image
                    figure.screenshot(path=str(output / "evidence.png"), timeout=milliseconds(10))
                    screenshots.append("evidence.png")

                # Reload the real saved URL; the application's startup code must restore the job.
                require(page.url == saved_url, "Saved job URL changed")
                page.reload(wait_until="domcontentloaded", timeout=milliseconds(30))
                check_display()
                expect(original_link).to_have_count(1, timeout=milliseconds(30))
                expect(page.locator("#connection")).to_have_text("", timeout=milliseconds(10))
                require(api_result() == final, "Terminal API result changed after reload")
                summary["saved_job_reload_verified"] = True
                request = json.loads((job_directory / "request.json").read_text())
                if saved_job is None and wire is None:
                    require(not request.get("time_window"), "Browser unexpectedly supplied a recording time")
                if saved_job is None:
                    submitted = summary["submitted_request"]
                    require(request.get("search") == submitted["search"]
                            and request.get("time_window") == submitted.get("time_window"),
                            "Persisted request differs from the UI submission")
                else:
                    require(digest(saved_job / "result.json") == summary["saved_result_sha256"],
                            "Original saved result changed")
                require(digest(job_directory / "input.mp3") == summary["source_sha256"], "Uploaded original bytes changed")
                summary["original_preserved"] = True
                require(not errors, "Browser reported uncaught page errors")
                summary["passed"] = True
            except BaseException:
                if page is not None and len(screenshots) < 2:
                    try:
                        page.screenshot(path=str(output / "failure.png"), timeout=5000)
                        screenshots.append("failure.png")
                    except Exception:
                        pass
                raise
            finally:
                if browser is not None:
                    browser.close()
    except BaseException as error:
        summary.update(passed=False, error=f"{type(error).__name__}: {error}")
    finally:
        # Repeated cancellation must not interrupt shutdown of our own service.
        for signum in old_handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            if process is not None:
                summary["service_shutdown"] = stop_service(process)
                require(summary["service_shutdown"]["clean"], "Service did not stop cleanly")
            if final is not None and job_directory is not None:
                retained = json.loads((job_directory / "result.json").read_text()) == final
                summary["terminal_result_preserved"] = retained
                require(retained, "Persisted terminal result differs from the API result")
        except BaseException as error:
            summary["passed"] = False
            summary["cleanup_error"] = f"{type(error).__name__}: {error}"
        finally:
            if log is not None:
                log.close()
            for signum, handler in old_handlers.items():
                signal.signal(signum, handler)
            summary["elapsed_s"] = time.monotonic() - started
            (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
