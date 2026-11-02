"""Normalize downloaded rolling captions and fingerprint the supplied MP4."""
import hashlib
import html
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / "data/source"
raw = (source / "video.en.vtt").read_text()
segments = []
previous = ""
for block in re.split(r"\n\s*\n", raw):
    lines = block.splitlines()
    timing = next((line for line in lines if " --> " in line), None)
    if timing is None:
        continue
    start = timing.split()[0]
    hh, mm, ss = map(float, start.split(":"))
    for line in lines[lines.index(timing) + 1:]:
        line = html.unescape(re.sub(r"<[^>]+>", "", line)).strip()
        if line and line != previous:
            segments.append({"time_s": hh * 3600 + mm * 60 + ss, "text": line})
            previous = line
(source / "transcript.json").write_text(json.dumps(segments, indent=2) + "\n")
(source / "transcript.txt").write_text("\n".join(
    f"[{int(s['time_s']) // 60:02d}:{int(s['time_s']) % 60:02d}] {s['text']}" for s in segments
) + "\n")
video = next(Path("/home/cinna/Downloads").glob("I discovered a sound*colsto*.mp4"))
digest = hashlib.file_digest(video.open("rb"), "sha256").hexdigest()
(source / "source_manifest.json").write_text(json.dumps({
    "video_path": str(video), "sha256": digest, "bytes": video.stat().st_size,
    "source_url": "https://www.youtube.com/watch?v=UytYrhYLOKI",
    "caption_type": "YouTube automatic English captions; uncorrected",
}, indent=2) + "\n")
print(f"Prepared {len(segments)} transcript lines; MP4 SHA256 {digest}")
