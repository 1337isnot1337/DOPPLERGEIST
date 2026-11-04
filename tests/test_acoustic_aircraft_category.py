"""Schema checks only; no audio generation or accuracy claims."""
import json
from copy import deepcopy
from pathlib import Path
import unittest

from dopplergeist.contracts import (
    event_measure_settings,
    validate_acoustic_aircraft_category,
    validate_event,
)


ROOT = Path(__file__).resolve().parents[1]


class AcousticAircraftCategoryTests(unittest.TestCase):
    def annotation(self, label="unknown"):
        return {
            "label": label,
            "method": "schema-check-only",
            "experimental": True,
        }

    def test_supported_labels_and_copy(self):
        for label in (
            "jet_like",
            "fixed_wing_propeller_like",
            "helicopter_like",
            "unknown",
        ):
            with self.subTest(label=label):
                value = self.annotation(label)
                result = validate_acoustic_aircraft_category(value)
                self.assertEqual(result, value)
                self.assertIsNot(result, value)

    def test_invalid_annotations(self):
        base = self.annotation()
        cases = [
            None,
            [],
            {**base, "label": "Boeing 737"},
            {**base, "label": []},
            {**base, "method": " "},
            {**base, "method": 123},
            {**base, "experimental": False},
            {**base, "experimental": 1},
            {**base, "probability": 0.9},
        ]
        cases.extend(
            {name: value for name, value in base.items() if name != missing}
            for missing in base
        )
        for index, value in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(ValueError):
                    validate_acoustic_aircraft_category(value)

    def test_existing_event_and_annotation_compatibility(self):
        event = json.loads(
            (ROOT / "docs/examples/detected-event.json").read_text()
        )
        original = deepcopy(event)
        baseline = validate_event(event)
        settings = event_measure_settings(event)
        self.assertEqual(event, original)

        annotated = deepcopy(event)
        annotated["acoustic_aircraft_category"] = self.annotation()
        before_validation = deepcopy(annotated)
        result = validate_event(annotated)
        self.assertEqual(annotated, before_validation)

        self.assertEqual(
            result["acoustic_aircraft_category"],
            annotated["acoustic_aircraft_category"],
        )
        self.assertEqual(event_measure_settings(annotated), settings)

        without_annotation = deepcopy(result)
        del without_annotation["acoustic_aircraft_category"]
        self.assertEqual(without_annotation, baseline)

        result["acoustic_aircraft_category"]["method"] = "changed-copy"
        self.assertEqual(
            annotated["acoustic_aircraft_category"]["method"],
            "schema-check-only",
        )

    def test_event_rejects_invalid_annotation(self):
        event = json.loads(
            (ROOT / "docs/examples/detected-event.json").read_text()
        )
        event["acoustic_aircraft_category"] = {
            **self.annotation(),
            "experimental": False,
        }
        with self.assertRaises(ValueError):
            validate_event(event)


if __name__ == "__main__":
    unittest.main()
