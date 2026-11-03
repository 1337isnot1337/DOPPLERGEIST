"""Live capture metadata must not invent recording clocks or retain URL tokens."""
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "capture_camera_audio", Path(__file__).resolve().parents[1] / "scripts/capture_camera_audio.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def test_untimed_live_segments_stay_without_a_recording_clock():
    playlist = "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:42\n#EXTINF:6.1,\na.ts?t=secret\n#EXTINF:6,\nb.ts\n"
    segments = capture.media_segments(playlist, "https://example.org/live/playlist.m3u8?token=secret")
    assert [row["sequence"] for row in segments] == [42, 43]
    assert all(row["broadcaster_start_utc"] is None for row in segments)
    assert segments[0]["url"] == "https://example.org/live/a.ts"


def test_broadcaster_clock_propagates_by_segment_duration_and_resets_at_a_gap():
    playlist = """#EXTM3U
#EXT-X-DISCONTINUITY-SEQUENCE:8
#EXT-X-PROGRAM-DATE-TIME:2026-11-02T19:49:23-05:00
#EXTINF:6.1,
a.ts
#EXTINF:6,
b.ts
#EXT-X-DISCONTINUITY
#EXTINF:6,
c.ts
#EXT-X-PROGRAM-DATE-TIME:2026-11-03T00:50:00Z
#EXTINF:6,
d.ts
"""
    segments = capture.media_segments(playlist, "https://example.org/live/")
    assert [row["broadcaster_start_utc"] for row in segments] == [
        "2026-11-03T00:49:23Z", "2026-11-03T00:49:29.100000Z", None, "2026-11-03T00:50:00Z"]


@pytest.mark.parametrize("line", ["#EXTINF:nan,", "#EXTINF:-1,", "#EXTINF:inf,"])
def test_invalid_media_duration_is_rejected(line):
    with pytest.raises(ValueError, match="duration"):
        capture.media_segments(f"#EXTM3U\n{line}\na.ts\n", "https://example.org/")


def test_naive_program_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        capture.media_segments("#EXT-X-PROGRAM-DATE-TIME:2026-11-03T00:50:00\n", "https://example.org/")


def test_public_page_metadata_is_json_not_executed_javascript():
    camera = {"hasaudio": "true", "stream": "https://example.org/p.m3u8?t=secret"}
    page = '<script>var json_base = ' + json.dumps({"cam": {"test": camera}}) + '; throw Error("do not run");</script>'
    assert capture.earthcam_metadata(page, "test") == camera
    assert capture.public_stream_url(camera["stream"]) == "https://example.org/p.m3u8"
    camera["hasaudio"] = "false"
    with pytest.raises(ValueError, match="audio"):
        capture.earthcam_metadata('var json_base=' + json.dumps({"cam": {"test": camera}}), "test")


def test_failed_http_capture_retains_status_and_no_false_clock(tmp_path, monkeypatch):
    from urllib.error import HTTPError

    def unavailable(*args):
        raise HTTPError("https://example.org/?token=secret", 503, "unavailable", {}, None)

    monkeypatch.setattr(capture, "fetch", unavailable)
    output = tmp_path / "receipt"
    receipt = capture.capture("https://example.org/", "test", output, 1)
    assert receipt["status"] == "failed"
    assert receipt["http_error_status"] == 503
    assert receipt["recording_start_utc"] is None
    assert receipt["recording_clock_established"] is False
    assert "secret" not in (output / "capture.json").read_text()


def test_real_transcode_keeps_audio_delay_relative_to_source_video(tmp_path):
    import subprocess
    import numpy as np

    source = tmp_path / "delayed-audio.ts"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=160x90:r=10:d=8", "-itsoffset", "2", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=16000:duration=6", "-map", "0:v", "-map", "1:a",
                    "-c:v", "mpeg2video", "-c:a", "aac", "-f", "mpegts", str(source)], check=True)
    output = tmp_path / "preserved.mp3"
    subprocess.run(capture.decoder_command(str(source), "", output, 8), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(output), "-f", "f32le",
                                   "-ac", "1", "-ar", "16000", "pipe:1"])
    samples = np.frombuffer(raw, dtype="<f4")
    assert capture.decoded_duration(output) == 8
    # Ordinary audio-only extraction rebases this tone to ~0 s and shortens the
    # result to ~6 s. Preserve its independent two-second source-timeline offset.
    assert np.max(np.abs(samples[:int(1.8 * 16000)])) < 0.001
    onset = np.flatnonzero(np.abs(samples) > 0.03)[0] / 16000
    assert onset == pytest.approx(2, abs=0.005)
