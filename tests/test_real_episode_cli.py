"""Exercise CLI routing and coverage failures with unmodified recorded PCM.

The two four-second excerpts are separate recordings for this software check.
No samples are generated, padded or joined, and proposal recall is not assessed.
"""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile


ROOT = Path(__file__).resolve().parents[1]


class RealEpisodeCli(unittest.TestCase):
    def test_explicit_routing_and_source_coverage(self):
        fixture = json.loads((ROOT / "tests/fixtures/real_discovery_normalization.json").read_text())
        self.assertEqual(fixture["sample_format"], "<f4")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, excerpt in enumerate(fixture["excerpts"]):
                raw = base64.b64decode(excerpt["pcm_f32le_base64"], validate=True)
                self.assertEqual(len(raw), excerpt["sample_count"] * 4)
                audio = root / f"recorded-excerpt-{index}.wav"
                wavfile.write(audio, fixture["sample_rate_hz"], np.frombuffer(raw, dtype="<f4"))
                for experimental in (False, True):
                    output = root / f"scan-{index}-{experimental}"
                    command = [sys.executable, "-m", "dopplergeist.cli", "discover", str(audio),
                               "--output", str(output)]
                    if experimental:
                        command.append("--experimental-episodes")
                    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    summary = json.loads(process.stdout)
                    artifact = json.loads((output / "discovery/discovery.json").read_text())
                    intake = json.loads((output / "intake/intake.json").read_text())
                    self.assertEqual(intake["sample_count"], excerpt["sample_count"])
                    self.assertEqual(summary["recording"]["duration_s"],
                                     excerpt["sample_count"] / fixture["sample_rate_hz"])
                    self.assertEqual(summary["events_found"], len(artifact["events"]))
                    if experimental:
                        self.assertTrue(summary["experimental_episodes"])
                        self.assertEqual(artifact["schema_version"], 2)
                        self.assertEqual(artifact["status"], "complete")
                        self.assertEqual(artifact["counts"]["raw_observations"], 2*artifact["counts"]["spectral_measurements"])
                        self.assertIn("chunk",artifact["counts_semantics"]["spectral_measurements"])
                        self.assertNotIn("spectral_measurements",artifact["rejections"]["counts"])
                        self.assertEqual(summary["canonical_proposals"], len(artifact["episodes"]))
                        self.assertIn("filter_size=64", " ".join(intake["decode"]["command"]))
                    else:
                        self.assertNotIn("experimental_episodes", summary)
                        self.assertNotIn("episodes", artifact)
                        self.assertNotIn("aresample", " ".join(intake["decode"]["command"]))
                        self.assertEqual((output / "intake/recording.f32").read_bytes(), raw)

            refused = root / "unrequested-experimental-option"
            process = subprocess.run(
                [sys.executable, "-m", "dopplergeist.cli", "discover", str(audio),
                 "--output", str(refused), "--max-frequency-hz", "6000"],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, 2)
            self.assertIn("require --experimental-episodes", process.stderr)
            self.assertFalse(refused.exists())

            unsupported = root / "unsupported-source-coverage"
            process = subprocess.run(
                [sys.executable, "-m", "dopplergeist.cli", "discover", str(audio),
                 "--output", str(unsupported), "--experimental-episodes", "--max-frequency-hz", "6000"],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, 2)
            artifact = json.loads((unsupported / "discovery/discovery.json").read_text())
            self.assertEqual(artifact["status"], "failed")
            self.assertEqual(artifact["failure"]["code"], "unsupported_frequency_coverage")
            self.assertFalse((unsupported / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
