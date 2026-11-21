"""Deep-scan Wake and decompile leads stay generic and fail soft."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.added_engines import _wake_findings, run_unverified_decompile

ADDR = "0x" + "aa" * 20


class AddedEngines(unittest.TestCase):
    def test_wake_names_do_not_keep_source(self):
        raw = json.dumps({
            "detections": [{
                "detector": "unused-import",
                "impact": "warning",
                "confidence": "high",
                "message": "function steal() public {}",
            }]
        })
        rows = _wake_findings(raw)
        self.assertEqual(rows[0].engine, "wake")
        self.assertEqual(rows[0].rule, "unused-import")
        self.assertTrue(rows[0].generic)
        self.assertNotIn("steal", rows[0].evidence)

    def test_verified_and_unfunded_do_not_decompile(self):
        verified = run_unverified_decompile(ADDR, "0x6000", 1_000, verified=True)
        poor = run_unverified_decompile(ADDR, "0x6000", 10)
        self.assertEqual(verified.status, "skipped")
        self.assertEqual(poor.status, "skipped")
        self.assertEqual(verified.findings, [])
        self.assertEqual(poor.findings, [])

    def test_missing_decompilers_skip(self):
        with patch("eth_scanner.deep.added_engines.heimdall_bin", return_value=None), \
             patch("eth_scanner.deep.added_engines.panoramix_bin", return_value=None):
            result = run_unverified_decompile(ADDR, "0x6000", 1_000)
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.findings, [])


if __name__ == "__main__":
    unittest.main()
