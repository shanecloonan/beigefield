"""Phase D labeled benchmark evaluation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.benchmark.eval import evaluate_labeled_benchmark, load_labeled


class BenchmarkEval(unittest.TestCase):
    def test_all_safe_cool_passes(self):
        data = load_labeled()
        preds = {str(e["address"]).lower(): "lane-a-cool" for e in data["entries"]}
        report = evaluate_labeled_benchmark(preds)
        self.assertEqual(report.false_positive, 0)
        self.assertTrue(report.passes_baseline)

    def test_safe_hot_is_false_positive(self):
        data = load_labeled()
        preds = {str(e["address"]).lower(): "lane-a-cool" for e in data["entries"]}
        # Force one safe address hot.
        safe = next(e for e in data["entries"] if e["label"] == "safe")
        preds[str(safe["address"]).lower()] = "lane-b-queue"
        report = evaluate_labeled_benchmark(preds)
        self.assertGreaterEqual(report.false_positive, 1)


if __name__ == "__main__":
    unittest.main()
