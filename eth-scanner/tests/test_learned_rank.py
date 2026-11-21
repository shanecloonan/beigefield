"""Ranking orders rows and does not change heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.rank import learn_order


class LearnedRank(unittest.TestCase):
    def test_a_higher_incident_mean_orders_by_leads(self):
        train = [
            {"label": "affected", "leads": 3},
            {"label": "safe", "leads": 1},
        ]
        result = learn_order(train, [
            {"address": "0x" + "bb" * 20, "leads": 0},
            {"address": "0x" + "aa" * 20, "leads": 4},
        ])
        self.assertEqual(result["weight"], 1)
        self.assertEqual(result["order"][0]["address"], "0x" + "aa" * 20)
        self.assertEqual(result["heat_contribution"], 0)
        self.assertTrue(all(row["heat_contribution"] == 0 for row in result["order"]))

    def test_a_noisy_detector_does_not_promote_anyone(self):
        train = [
            {"label": "affected", "leads": 1},
            {"label": "safe", "leads": 4},
        ]
        result = learn_order(train, [
            {"address": "0x" + "bb" * 20, "leads": 9},
            {"address": "0x" + "aa" * 20, "leads": 0},
        ])
        self.assertEqual(result["weight"], 0)
        self.assertEqual(
            [row["address"] for row in result["order"]],
            ["0x" + "aa" * 20, "0x" + "bb" * 20],
        )
        self.assertEqual(result["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
