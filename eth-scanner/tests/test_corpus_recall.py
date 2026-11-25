"""The recall baseline is locked. A dropped detector fails the gate."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.benchmark.corpus_recall import recall_report


class CorpusRecall(unittest.TestCase):
    def test_baseline_is_nine_of_ten(self):
        report = recall_report()
        self.assertEqual(report["labeled"], 10)
        self.assertEqual(report["hits"], 9)
        self.assertEqual(report["misses"], 1)
        self.assertEqual(report["recall"], 0.9)
        self.assertTrue(report["passes_baseline"])
        self.assertEqual(report["heat_contribution"], 0)
        missed = [row["id"] for row in report["rows"] if not row["hit"]]
        self.assertEqual(missed, ["signature-replay"])
        blob = json.dumps(report)
        self.assertNotIn("payable(msg.sender)", blob)
        self.assertNotIn("target.delegatecall", blob)
        self.assertNotIn("http", blob)
