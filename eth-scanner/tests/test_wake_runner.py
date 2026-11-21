"""Wake leads keep detector names and drop source snippets."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.wake_runner import parse_wake, run_wake

RAW = json.dumps({
    "detections": [{
        "detector": "unused-import",
        "impact": "warning",
        "confidence": "high",
        "message": "function steal() public { selfdestruct(payable(msg.sender)); }",
        "source": "contract X { function steal() public {} }",
    }]
})


class WakeRunner(unittest.TestCase):
    def test_json_keeps_the_name_and_drops_the_snippet(self):
        rows = parse_wake(RAW)
        self.assertEqual(rows, [{
            "detector": "unused-import",
            "impact": "warning",
            "confidence": "high",
            "heat_contribution": 0,
        }])
        blob = json.dumps(rows)
        self.assertNotIn("steal", blob)
        self.assertNotIn("selfdestruct", blob)
        self.assertEqual(parse_wake("not json and function steal() {}"), [])

    def test_a_missing_binary_skips(self):
        report = run_wake("contract X {}", which=lambda name: None)
        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["detections"], [])
        self.assertEqual(report["heat_contribution"], 0)

    def test_a_crash_keeps_no_detections(self):
        def boom(source):
            raise RuntimeError("wake broke")

        report = run_wake("contract X {}", runner=boom)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["detections"], [])
        self.assertEqual(report["heat_contribution"], 0)

    def test_injected_json_is_evidence_only(self):
        report = run_wake("contract X {}", runner=lambda source: RAW)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["detections"][0]["detector"], "unused-import")
        self.assertTrue(report["evidence_only"])
        self.assertEqual(report["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
