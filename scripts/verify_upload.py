"""Exercise the real HTTP upload path; join reference coordinates afterward.

This is an explicit, potentially expensive acceptance run, not a mocked CI test.
The server must already be running with its flight/terrain configuration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from pyproj import Geod
import requests


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def verify(url, audio, request_path, output, timeout_s, truth_path=None):
    output.mkdir(parents=True, exist_ok=False)
    request = json.loads(request_path.read_text())
    if not isinstance(request, dict) or "audio_path" in request:
        raise ValueError("Use upload metadata without audio_path")
    source_hash = digest(audio)
    write(output / "request.json", request)
    receipt = {"audio_sha256": source_hash, "audio_bytes": audio.stat().st_size,
               "request_sha256": digest(request_path), "url": url,
               "runner_sha256": digest(__file__),
               "truth_sent_to_server": False, "case_passed": False}
    began = time.monotonic()
    session = requests.Session()

    def get(path):
        response = session.get(url + path, timeout=30)
        response.raise_for_status()
        return response

    try:
        write(output / "capabilities.json", get("/api/capabilities").json())
        # HTTP delivery alone is not a browser interaction check.
        (output / "index.html").write_bytes(get("/").content)
        with audio.open("rb") as source:
            response = session.post(url + "/api/jobs", data=source, timeout=(30, 300),
                                    headers={"Content-Type": "application/octet-stream",
                                             "Content-Length": str(audio.stat().st_size),
                                             "X-Filename": audio.name,
                                             "X-Dopplergeist-Request": json.dumps(request)})
        response.raise_for_status()
        if response.status_code != 202:
            raise ValueError(f"Upload returned {response.status_code}, expected 202")
        result = response.json()
        job_path = "/api/jobs/" + result["job_id"]
        receipt["job_id"] = result["job_id"]
        states = []
        while True:
            if not states or result != states[-1]["result"]:
                states.append({"elapsed_s": time.monotonic() - began, "result": result})
                write(output / "states.json", states)
                print(result["status"], result.get("stage", ""), flush=True)
            if result["status"] not in {"queued", "running"}:
                break
            if time.monotonic() - began >= timeout_s:
                # Cancel this runner's job and retain its partial evidence.
                response = session.post(url + job_path + "/cancel", timeout=30)
                response.raise_for_status()
                write(output / "cancel-result.json", response.json())
                raise TimeoutError(f"Upload job exceeded {timeout_s} seconds")
            time.sleep(1)
            result = get(job_path).json()
        write(output / "result.json", result)
        receipt["status"] = result["status"]
        receipt["reason_code"] = result.get("reason_code")
        receipt["coverage"] = result.get("coverage")
        listing = get(job_path + "/artifacts").json()
        write(output / "server-artifacts.json", listing)
        artifacts = output / "artifacts"
        artifacts.mkdir()
        hashes = []
        for item in listing["artifacts"]:
            relative = Path(item["path"])
            target = artifacts / relative
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Server returned an unsafe artifact path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with session.get(url + job_path + "/artifacts/" + relative.as_posix(),
                             stream=True, timeout=60) as response:
                response.raise_for_status()
                with target.open("wb") as destination:
                    for block in response.iter_content(1024 * 1024):
                        destination.write(block)
            if target.stat().st_size != item["bytes"]:
                raise ValueError(f"Incomplete artifact: {relative}")
            hashes.append({"path": relative.as_posix(), "sha256": digest(target),
                           "bytes": target.stat().st_size})
        write(output / "artifact-hashes.json", hashes)
        original = next((row for row in hashes if row["path"] == "input" + audio.suffix.lower()), None)
        if original is None or original["sha256"] != source_hash:
            raise ValueError("Downloaded original does not match uploaded audio")
        receipt["upload_roundtrip_verified"] = True
        # This is the first reference read. Neither request nor server receives it.
        if truth_path is not None:
            truth = json.loads(truth_path.read_text())
            receipt["reference_sha256"] = digest(truth_path)
            receipt["reference_provenance"] = truth.get("provenance")
            if result["status"] == "succeeded":
                location = result["candidates"][0]
                distance = Geod(ellps="WGS84").inv(
                    truth["lon"], truth["lat"], location["lon"], location["lat"])[2]
                receipt["location_error_m"] = distance
                coverage = result.get("coverage", {})
                receipt["case_passed"] = (distance <= 100
                                           and coverage.get("search_complete") is True
                                           and coverage.get("data_status") == "available"
                                           and bool(result.get("events")))
        receipt["scope"] = (
            "One actual upload and artifact roundtrip; reference provenance and "
            "search/data coverage require separate review. HTTP delivery is not "
            "browser interaction or national holdout validation.")
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt["elapsed_s"] = time.monotonic() - began
        write(output / "receipt.json", receipt)
        session.close()
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--truth", type=Path)
    args = parser.parse_args()
    outcome = verify(args.url.rstrip("/"), args.audio, args.request, args.output,
                     args.timeout, args.truth)
    print(json.dumps(outcome, indent=2))
    raise SystemExit(0 if outcome["case_passed"] else 1)
