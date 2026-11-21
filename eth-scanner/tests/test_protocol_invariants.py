"""A protocol's heat comes only from a kept property that fails locally."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.protocol import protocol_report


class ProtocolInvariants(unittest.TestCase):
    def test_an_oracle_is_a_witness_and_adds_no_heat(self):
        result = protocol_report({
            "vault": "0x" + "aa" * 20,
            "oracle": "0x" + "bb" * 20,
        })
        self.assertTrue(result["vault_present"])
        self.assertIn("erc4626-solvency", result["kept"])
        self.assertEqual(result["witnesses"][0]["role"], "oracle")
        self.assertEqual(result["heat_contribution"], 0)

    def test_heat_requires_a_local_failure_that_passed_the_baseline(self):
        parts = {"vault": "0x" + "aa" * 20}
        quiet = protocol_report(parts, local_failures={"erc4626-solvency"})
        self.assertEqual(quiet["heat_contribution"], 1)
        blocked = protocol_report(
            parts,
            baseline_failures={"erc4626-solvency"},
            local_failures={"erc4626-solvency"},
        )
        self.assertEqual(blocked["heat_contribution"], 0)
        self.assertNotIn("erc4626-solvency", blocked["kept"])


if __name__ == "__main__":
    unittest.main()
