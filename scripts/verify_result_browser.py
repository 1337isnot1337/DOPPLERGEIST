#!/usr/bin/env python3
"""Read a frozen terminal job through the real installed service and browser.

This verifies readback and rendering, not a new upload or scientific analysis.
The fixture is copied to a fresh job root and every served artifact is checked
against its original bytes. No request interception or fabricated result is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.parse import quote
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
from verify_upload_browser import verify_candidate_cards


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = args.fixture.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    expected = json.loads((fixture / "result.json").read_text())
    job_id = expected["job_id"]
    if fixture.name != job_id or expected["status"] not in {"needs_input", "succeeded", "inconclusive", "failed", "cancelled"}:
        raise ValueError("Expected an unchanged terminal job directory")
    original = {str(p.relative_to(fixture)): digest(p) for p in fixture.rglob("*") if p.is_file()}
    copied = output / "jobs" / job_id
    shutil.copytree(fixture, copied)
    write(output / "input-manifest.json", original)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    command = [str(args.python.absolute()), "-m", "dopplergeist.cli", "serve", "--jobs", str(output / "jobs"), "--port", str(port)]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["OPENBLAS_NUM_THREADS"] = "1"
    report = {"scope": "unchanged_terminal_job_readback_only", "command": command, "passed": False}
    with (output / "server.log").open("w") as log:
        server = subprocess.Popen(command, env=env, cwd=output, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Readback service exited during startup")
                try:
                    with urlopen(base + "/api/capabilities", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(.1)
            else:
                raise TimeoutError("Readback service did not start")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1100}, timezone_id="UTC")
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                try:
                    response = context.request.get(f"{base}/api/jobs/{job_id}")
                    assert response.ok and response.json() == expected, "API changed the frozen result"
                    write(output / "api-result.json", response.json())
                    listing = context.request.get(f"{base}/api/jobs/{job_id}/artifacts").json()["artifacts"]
                    downloads = []
                    assert {item["path"] for item in listing} == set(original), "Artifact listing changed"
                    for item in listing:
                        downloaded = context.request.get(f"{base}/api/jobs/{job_id}/artifacts/{quote(item['path'], safe='/')}")
                        body = downloaded.body()
                        sha = hashlib.sha256(body).hexdigest()
                        assert downloaded.ok and len(body) == item["bytes"] and sha == original[item["path"]], item["path"]
                        downloads.append({**item, "sha256": sha, "http_status": downloaded.status})
                    write(output / "artifact-roundtrip.json", downloads)
                    page.goto(f"{base}/?job={job_id}", wait_until="networkidle")
                    display = expected["status"].replace("_", " ")
                    page.wait_for_function("s => document.querySelector('#status').textContent === s", arg=display)
                    page.wait_for_function("() => document.querySelector('#artifacts').children.length > 0")
                    count = len(expected.get("candidates", []))
                    cards = page.locator("#candidates .candidate")
                    candidate_readback = verify_candidate_cards(page, expected.get("candidates", []))
                    page.screenshot(path=str(output / "desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    layout = lambda: page.evaluate("({viewport_width:innerWidth,document_width:document.documentElement.scrollWidth})")
                    collapsed = layout()
                    assert collapsed["document_width"] <= collapsed["viewport_width"]
                    page.screenshot(path=str(output / "mobile.png"), full_page=True)
                    if count > 5:
                        details = page.locator("#candidates details")
                        assert details.count() == 1 and not details.get_attribute("open")
                        assert details.locator("summary").text_content() == f"{count - 5} additional hypotheses"
                        details.locator("summary").click()
                        assert sum(card.is_visible() for card in cards.all()) == count
                    expanded = layout()
                    assert expanded["document_width"] <= expanded["viewport_width"]
                    page.screenshot(path=str(output / "mobile-expanded-viewport.png"))
                    page.reload(wait_until="networkidle")
                    page.wait_for_function("s => document.querySelector('#status').textContent === s", arg=display)
                    assert page.locator("#candidates .candidate").count() == count
                    assert not errors, errors
                    report.update(passed=True, browser=browser.version, status=expected["status"], candidate_count=count,
                                  **{k: v for k, v in candidate_readback.items() if k != "candidate_count"}, expanded_visible_candidates=count,
                                  mobile_collapsed=collapsed, mobile_expanded=expanded, artifact_count=len(downloads),
                                  reloaded_job_verified=True, javascript_errors=errors)
                finally:
                    (output / "page.txt").write_text(page.locator("body").inner_text())
                    context.tracing.stop(path=str(output / "trace.zip"))
                    context.close()
                    browser.close()
            after = {str(p.relative_to(copied)): digest(p) for p in copied.rglob("*") if p.is_file()}
            assert after == original, "Readback modified the copied scientific artifacts"
            report["all_job_bytes_unchanged"] = True
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
            write(output / "report.json", report)
    print(json.dumps({key: report[key] for key in ("scope", "passed", "candidate_count", "artifact_count", "mobile_collapsed", "mobile_expanded")}))


if __name__ == "__main__":
    main()
