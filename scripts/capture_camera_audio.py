"""Capture public webcam audio with explicit clock and map-reference provenance.

EarthCam and HDOnTap pages expose normal public HLS URLs in JSON player metadata.
This tool uses those URLs without credentials. Captured bytes, HTTP/capture times
and broadcaster segment timestamps are distinct; absent segment timestamps never
become UTC.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class AudioNotAdvertised(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def public_stream_url(url):
    """Exclude transient stream authorization queries from published receipts."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def fetch(url, referer):
    started = utc_now()
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
    with urlopen(request, timeout=30) as response:
        data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("Metadata response exceeds 8 MiB")
        return data, {"started_utc": started, "finished_utc": utc_now(),
                      "http_status": response.status, "http_date": response.headers.get("Date"),
                      "sha256": sha256(data), "bytes": len(data)}


def earthcam_metadata(html, camera):
    match = re.search(r"\bvar\s+json_base\s*=\s*", html)
    if not match:
        raise ValueError("Page does not expose EarthCam json_base metadata")
    value, _ = json.JSONDecoder().raw_decode(html[match.end():])
    selected = value["cam"][camera]
    if str(selected.get("hasaudio", "")).lower() != "true":
        raise AudioNotAdvertised("Selected camera does not advertise audio")
    stream = selected.get("stream")
    if not stream or urlsplit(stream).scheme not in {"http", "https"}:
        raise ValueError("Selected camera has no public HTTP stream")
    return selected


def hdontap_metadata(html):
    """Read the ordinary public embed's JSON player data without executing JS."""
    class PlayerData(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inside = False
            self.chunks = []

        def handle_starttag(self, tag, attrs):
            if tag == "script" and dict(attrs).get("id") == "player-data":
                self.inside = True

        def handle_data(self, data):
            if self.inside:
                self.chunks.append(data)

        def handle_endtag(self, tag):
            if tag == "script":
                self.inside = False

    parser = PlayerData()
    parser.feed(html)
    if not parser.chunks:
        raise ValueError("Public HDOnTap embed has no JSON player-data")
    data = json.loads("".join(parser.chunks))
    stream = data.get("streamSrc")
    if not isinstance(stream, str) or urlsplit(stream).scheme not in {"http", "https"}:
        raise ValueError("Public HDOnTap embed has no HTTP streamSrc")
    return {"stream": stream, "name": "HDOnTap public embed", "hasaudio": None}


def media_segments(text, base_url):
    """Keep broadcaster PDT only across contiguous, timed HLS segments."""
    timestamp = None
    duration = None
    sequence = 0
    segments = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            sequence = int(line.partition(":")[2])
        elif line.startswith("#EXT-X-DISCONTINUITY"):
            # DISCONTINUITY-SEQUENCE is a counter, not a new boundary.
            if line == "#EXT-X-DISCONTINUITY":
                timestamp = None
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            raw = line.partition(":")[2]
            timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("HLS program timestamp has no timezone")
            timestamp = timestamp.astimezone(timezone.utc)
        elif line.startswith("#EXTINF:"):
            duration = float(line.partition(":")[2].split(",")[0])
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("Invalid HLS segment duration")
        elif line and not line.startswith("#"):
            if duration is None:
                raise ValueError("Media URI lacks EXTINF duration")
            segments.append({"sequence": sequence, "url": public_stream_url(urljoin(base_url, line)),
                             "duration_s": duration,
                             "broadcaster_start_utc": timestamp.isoformat().replace("+00:00", "Z") if timestamp else None})
            sequence += 1
            if timestamp is not None:
                timestamp += timedelta(seconds=duration)
            duration = None
    return segments


def decoder_command(stream, page_url, audio_path, duration_s):
    command = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-copyts", "-start_at_zero"]
    if urlsplit(stream).scheme in {"http", "https"}:
        command += ["-rw_timeout", "15000000", "-user_agent", "Mozilla/5.0",
                    "-headers", f"Referer: {page_url}\r\n"]
    return command + ["-i", str(stream), "-t", str(duration_s), "-map", "0:a:0", "-vn",
                      "-ac", "1", "-ar", "16000", "-af", "aresample=async=1:first_pts=0",
                      "-c:a", "libmp3lame", "-b:a", "64k", str(audio_path),
                      # Keeping video mapped prevents ffmpeg from rebasing input
                      # time to the first audio packet and discarding an A/V delay.
                      # Copying to null retains its clock without saving video.
                      "-t", str(duration_s), "-map", "0:v:0", "-c:v", "copy", "-an", "-f", "null", os.devnull]


def decoded_duration(path):
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
               "-ar", "16000", "-f", "f32le", "pipe:1"]
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        count = 0
        while block := process.stdout.read(1024 * 1024):
            count += len(block)
        if process.wait() != 0 or count % 4:
            raise ValueError("Captured MP3 cannot be decoded to complete float32 samples")
    return count / (4 * 16000)


def capture(page_url, camera, output, duration_s, provider="earthcam"):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema_version": 1, "source_page": page_url, "camera": camera, "provider": provider,
               "requested_duration_s": duration_s, "status": "failed",
               "recording_start_utc": None, "recording_clock_established": False,
               "truth_used_for_event_detection": False, "location_validation_eligible": False,
               "implementation_sha256": sha256(Path(__file__).read_bytes())}
    try:
        page, receipt["page_fetch"] = fetch(page_url, page_url)
        if provider == "earthcam":
            metadata = earthcam_metadata(page.decode(), camera)
        elif provider == "hdontap":
            metadata = hdontap_metadata(page.decode())
        else:
            raise ValueError("Unsupported public camera provider")
        stream = metadata["stream"]
        receipt["camera_name"] = metadata.get("name")
        receipt["source_audio_advertised"] = metadata.get("hasaudio")
        receipt["stream_url"] = public_stream_url(stream)
        receipt["stream_url_sha256"] = sha256(stream.encode())
        receipt["provider_map_reference"] = ({
            "lat": float(metadata["map_lat"]), "lon": float(metadata["map_long"]),
            "kind": "provider_map_marker", "uncertainty_m": None,
            "source": page_url, "timezone": metadata.get("timezone")}
            if metadata.get("map_lat") is not None and metadata.get("map_long") is not None else None)
        master, receipt["playlist_fetch"] = fetch(stream, page_url)
        playlist_url = stream
        playlist = master.decode()
        if "#EXT-X-STREAM-INF:" in playlist:
            variant = next(line.strip() for line in playlist.splitlines()
                           if line.strip() and not line.startswith("#"))
            playlist_url = urljoin(stream, variant)
            body, receipt["media_playlist_fetch"] = fetch(playlist_url, page_url)
            playlist = body.decode()
        receipt["initial_media_segments"] = media_segments(playlist, playlist_url)
        receipt["broadcaster_segment_clock_present"] = any(
            segment["broadcaster_start_utc"] for segment in receipt["initial_media_segments"])
        receipt["clock_limitations"] = [
            "Capture/HTTP times are receipt times, not microphone sample-zero UTC.",
            "A map marker does not establish a surveyed microphone coordinate or uncertainty.",
            "Broadcaster segment timestamps, if present, still require binding to the first captured audio sample."]
        command = decoder_command(stream, page_url, output / "audio.mp3", duration_s)
        receipt["audio_timeline"] = "source A/V timestamps, rebased together; audio gaps may be padded by aresample"
        receipt["decoder_command_redacted"] = [
            public_stream_url(value) + "?[query omitted]" if value == stream else value for value in command]
        receipt["ffmpeg_version"] = subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]
        # The complete URL stays in memory and the local ignored decoder log;
        # published metadata retains its hash and a URL without transient query.
        receipt["capture_started_utc"] = utc_now()
        began = time.monotonic()
        with (output / "decoder.log").open("wb") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                receipt["decoder_exit_code"] = process.wait(timeout=duration_s + 90)
            except subprocess.TimeoutExpired:
                receipt["timed_out"] = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                receipt["decoder_exit_code"] = process.returncode
        receipt["capture_finished_utc"] = utc_now()
        receipt["capture_elapsed_s"] = time.monotonic() - began
        audio = output / "audio.mp3"
        if audio.is_file():
            receipt["audio"] = {"path": "audio.mp3", "bytes": audio.stat().st_size,
                                "sha256": sha256(audio.read_bytes())}
        if receipt["decoder_exit_code"] == 0 and receipt.get("audio", {}).get("bytes", 0) > 0:
            receipt["audio_probe"] = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels",
                "-of", "json", str(audio)], text=True, timeout=20))
            actual_duration = decoded_duration(audio)
            receipt["decoded_duration_s"] = actual_duration
            receipt["status"] = "captured" if abs(actual_duration - duration_s) <= 0.05 else "partial_capture"
    except Exception as exc:
        # URLs in provider exceptions can contain expiring access queries.
        receipt["error_type"] = type(exc).__name__
        if isinstance(exc, HTTPError):
            receipt["http_error_status"] = exc.code
        receipt["error"] = "Capture failed; inspect local source/decoder evidence."
        if isinstance(exc, AudioNotAdvertised):
            receipt["reason_code"] = "source_has_no_advertised_audio"
            receipt["error"] = "Selected camera does not advertise audio."
    (output / "capture.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", required=True)
    parser.add_argument("--provider", choices=("earthcam", "hdontap"), default="earthcam")
    parser.add_argument("--camera", help="EarthCam camera key, or optional source alias for HDOnTap")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=300)
    args = parser.parse_args(argv)
    if args.provider == "earthcam" and not args.camera:
        parser.error("--camera is required for EarthCam")
    if not math.isfinite(args.duration_s) or not 0 < args.duration_s <= 3600:
        parser.error("--duration-s must be finite and between 0 and 3600")
    if urlsplit(args.page).scheme not in {"http", "https"} or "\n" in args.page or "\r" in args.page:
        parser.error("--page must be an HTTP URL without header control characters")
    receipt = capture(args.page, args.camera, args.output, args.duration_s, args.provider)
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return 0 if receipt["status"] == "captured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
