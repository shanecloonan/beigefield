"""L1 and L2 numbers are compared as leads. Heat stays 0."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.l2_invariants import l2_invariants


def _state(result, name):
    return next(row["state"] for row in result["checks"] if row["id"] == name)


class L2Invariants(unittest.TestCase):
    def test_a_sequenced_block_inside_the_l1_head_holds(self):
        result = l2_invariants("arb", l2_head=900, l1_block=100, l1_head=100)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["chain"], "arbitrum")
        self.assertEqual(_state(result, "l1-present"), "held")
        self.assertEqual(_state(result, "l1-not-ahead"), "held")
        self.assertEqual(result["heat_contribution"], 0)

    def test_a_sequenced_block_past_the_l1_head_is_a_lead(self):
        result = l2_invariants("base", l2_head=10, l1_block=11, l1_head=10)
        self.assertEqual(_state(result, "l1-not-ahead"), "violated")
        self.assertEqual(result["heat_contribution"], 0)

    def test_a_missing_l1_number_stays_unknown(self):
        result = l2_invariants("arbitrum", l2_head=10, l1_block=None, l1_head=10)
        self.assertEqual(_state(result, "l1-present"), "unknown")
        self.assertEqual(_state(result, "l1-not-ahead"), "unknown")
        self.assertEqual(result["heat_contribution"], 0)

    def test_ethereum_is_not_an_l2(self):
        result = l2_invariants("ethereum", l2_head=1, l1_block=1, l1_head=1)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "not an l2")
        self.assertEqual(result["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
