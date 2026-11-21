"""Manual-review notes may lower heat. They never raise it."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.triage import apply_maybe, triage_report


class MaybeTriage(unittest.TestCase):
    def test_a_note_can_lower_heat_on_a_maybe_row(self):
        result = apply_maybe(heat=5, bucket="manual-review", lower_by=2, note="getter only")
        self.assertEqual(result["heat"], 3)
        self.assertEqual(result["heat_contribution"], -2)
        self.assertEqual(result["annotation"], "getter only")

    def test_heat_cannot_go_below_zero_or_increase(self):
        floored = apply_maybe(heat=1, bucket="manual-review", lower_by=9, note="noise")
        self.assertEqual(floored["heat"], 0)
        self.assertLessEqual(floored["heat_contribution"], 0)
        raised = apply_maybe(heat=4, bucket="manual-review", lower_by=-3, note="still a maybe")
        self.assertEqual(raised["heat"], 4)
        self.assertEqual(raised["heat_contribution"], 0)

    def test_other_buckets_are_left_alone(self):
        result = apply_maybe(heat=8, bucket="lane-b-queue", lower_by=5, note="ignore")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["heat"], 8)
        self.assertEqual(result["heat_contribution"], 0)
        self.assertEqual(result["annotation"], "")

    def test_without_a_key_or_a_note_heat_stays(self):
        saved = {name: os.environ.pop(name, None) for name in ("OPENAI_API_KEY", "ETH_SCANNER_LLM_API_KEY")}
        try:
            result = triage_report(heat=6, bucket="manual-review")
        finally:
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["heat"], 6)
        self.assertEqual(result["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
