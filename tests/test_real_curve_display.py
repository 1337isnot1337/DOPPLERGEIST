"""Render saved real measurements without generating audio or running search.

These are display checks, not aircraft identification or location evaluation.
"""
import gzip
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from dopplergeist.discovery import DiscoverySettings, _event_plot_geometry, _plot_group_curves

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "evidence/audio/w1-fragments-20261102"


def reference():
    recording = json.loads((REFERENCE / "reference-summary.json").read_text())["recording"]
    events = json.loads((REFERENCE / "reference-discovery/discovery.json").read_text())["events"]
    return SimpleNamespace(metadata=recording), events


def test_real_overview_keeps_every_supplied_ridge(tmp_path):
    recording, events = reference()
    # The actual six-ridge overview tests visibility, without asserting that
    # these curves constitute one harmonic source.
    output = tmp_path / "overview.png"
    plot = _plot_group_curves(recording, "Recorded ridge overview", events, output,
                              DiscoverySettings())
    times = [point["time_s"] for event in events for point in event["ridge"]]
    assert max(times) - min(times) > 300
    assert plot["start_s"] <= min(times)
    assert plot["end_s"] >= max(times)
    assert plot["ridges"] == len(events)
    assert output.stat().st_size > 0


def test_real_display_geometry_is_bounded_and_marks_crops():
    recording, events = reference()
    truncated = []
    for event in events:
        plot = _event_plot_geometry(recording, event, DiscoverySettings())
        sr = recording.metadata["sample_rate_hz"]
        sample_count = round(plot["end_s"] * sr) - round(plot["start_s"] * sr)
        window = round(plot["window_s"] * sr)
        hop = round(plot["hop_s"] * sr)
        assert 1 + (sample_count - window) // hop <= 400
        assert plot["hop_s"] >= 0.05
        assert plot["end_s"] - plot["start_s"] <= 80
        assert plot["truncated"] == (plot["start_s"] > event["start_s"]
                                     or plot["end_s"] < event["end_s"])
        truncated.append(plot["truncated"])
    assert any(truncated) and not all(truncated)


def test_browser_segments_and_gap_flags_on_real_measurements():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the browser display check")
    events = []
    with gzip.open(ROOT / "benchmarks/acoustic-episodes-349/observations.jsonl.gz", "rt") as source:
        for line in source:
            case = json.loads(line)
            for arm in ("baseline", "new", "wide"):
                if case.get(arm):
                    events.extend(case[arm]["events"])
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = vm.createContext({});
// Load pure display functions without starting the app or discovery.
for (const name of ['medianValue', 'ridgeGapInfo', 'ridgeShape', 'ridgeSegments']) {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf('\n}\n', start) + 3;
  assert.ok(start >= 0 && end > start);
  vm.runInContext(source.slice(start, end), context);
}
const events = JSON.parse(fs.readFileSync(0, 'utf8'));
let gapped = 0, shortGaps = 0;
for (const event of events) {
  const gaps = context.ridgeGapInfo(event);
  const segments = context.ridgeSegments(event);
  assert.equal(segments.length, gaps.count + 1);
  assert.deepEqual(segments[0][0], event.ridge[0]);
  assert.deepEqual(segments.at(-1).at(-1), event.ridge.at(-1));
  if (gaps.count) {
    assert.equal(context.ridgeShape(event).warning, 'gap');
    gapped += 1;
  }
  if (event.ridge.length < 8 && gaps.count) {
    assert.equal(context.ridgeShape(event).warning, 'gap');
    shortGaps += 1;
  }
}
assert.ok(gapped > 0, 'The real corpus must exercise measured gaps');
console.log(`${events.length} real ridges checked; ${gapped} gapped, ${shortGaps} short gapped`);
"""
    completed = subprocess.run([node, "-e", script, str(ROOT / "src/dopplergeist/web/app.js")],
                               input=json.dumps(events), text=True, capture_output=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
