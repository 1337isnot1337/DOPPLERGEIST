"""Upload through the actual browser UI and verify its original-file download.

Run with codex-isolated-desktop. Requires the optional Playwright Python package
and a local Chromium executable. This checks UI behavior, not location accuracy.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def verify(url, audio, metadata, output):
    if (set(metadata) - {"schema_version", "time_window", "search"}
            or metadata.get("schema_version") != 1
            or metadata.get("search", {"coverage": "conus"}) != {"coverage": "conus"}):
        raise ValueError("The browser UI accepts version-one CONUS requests without event or location hints")
    if (metadata.get("time_window") or {}).get("source", "user") != "user":
        raise ValueError("The browser form records user-supplied time evidence")
    runtime = Path(os.environ["XDG_RUNTIME_DIR"])
    state = dict(line.split("=", 1) for line in
                 (runtime / "codex-isolated-desktop/state").read_text().splitlines())
    state = {key: shlex.split(value)[0] if value else "" for key, value in state.items()}
    if (os.environ.get("WAYLAND_DISPLAY") != state["wayland_display"]
            or state["wayland_display"] == state["host_wayland"]
            or os.environ.get("DISPLAY")):
        raise RuntimeError("Run through codex-isolated-desktop on its isolated display")
    # The helper sets Wayland but can retain the host compositor variable.
    isolated_instance = Path(state["hypr_dir"]).name
    if isolated_instance == os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        raise RuntimeError("Isolated compositor must differ from the inherited host compositor")
    os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = isolated_instance
    output.mkdir(parents=True, exist_ok=False)
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url, wait_until="networkidle")
            expect(page).to_have_title(re.compile("^DOPPLERGEIST"))
            page.locator("#audio").set_input_files(str(audio))
            window = metadata.get("time_window")
            if window:
                for name, field in (("start", "start_utc"), ("end", "end_utc")):
                    stamp = datetime.fromisoformat(window[field].replace("Z", "+00:00"))
                    if stamp.tzinfo is None:
                        raise ValueError("Recording timestamp requires an explicit timezone")
                    if stamp.microsecond:
                        raise ValueError("The current browser form requires whole-second timestamps")
                    value = stamp.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
                    page.locator("#" + name).fill(value)
                page.locator("#time-source").fill(window.get("source_detail", ""))
            page.locator("#submit").click()
            expect(page.locator("#status")).to_have_text(
                re.compile("^(needs input|succeeded|inconclusive|failed|cancelled)$"), timeout=3600000)
            page.locator("#downloads summary").click()
            expect(page.locator("#artifacts a").first).to_be_visible(timeout=30000)
            receipt = {"title": page.title(), "url": page.url,
                       "job_id": parse_qs(urlparse(page.url).query)["job"][0],
                       "status": page.locator("#status").inner_text(),
                       "message": page.locator("#message").inner_text(),
                       "required_input": page.locator("#required").inner_text(),
                       "artifact_links": page.locator("#artifacts a").all_text_contents(),
                       "page_errors": errors,
                       "isolated_wayland_display": state["wayland_display"],
                       "isolated_compositor": isolated_instance,
                       "scope": "Actual browser upload, displayed result and original download; no accuracy claim."}
            with Path(__file__).open("rb") as source:
                receipt["runner_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
            original = "input" + audio.suffix.lower()
            with page.expect_download() as event:
                page.get_by_role("link", name=original, exact=True).click()
            destination = output / original
            event.value.save_as(destination)
            with audio.open("rb") as source:
                expected_hash = hashlib.file_digest(source, "sha256").hexdigest()
            with destination.open("rb") as source:
                actual_hash = hashlib.file_digest(source, "sha256").hexdigest()
            receipt["source_sha256"] = expected_hash
            receipt["download_sha256"] = actual_hash
            page.screenshot(path=str(output / "result.png"), full_page=True)
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            assert actual_hash == expected_hash, "Original download differs from upload"
            assert not errors, errors
            return receipt
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.url, args.audio, json.loads(args.request.read_text()), args.output), indent=2))
