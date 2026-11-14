"""Drain probability: profit breaks rank high, accounting quirks stay low."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.drain import score_drain, simulate_local_vault
from eth_scanner.heat import evidence_heat, should_promote_lane_b
from eth_scanner.known_safe import is_known_safe

LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"
BENTO = "0xf5bce5077908a1b7370b9ae04adc565ebd643966"


class DrainScore(unittest.TestCase):
    def test_known_safe_proves_no_break(self):
        for addr, name in ((LINK, "LinkToken"), (BENTO, "BentoBoxV1")):
            self.assertTrue(is_known_safe(address=addr, contract_name=name)[0])
        safe = simulate_local_vault("safe")
        self.assertFalse(safe["profit_invariant_broke"])
        self.assertLess(safe["drain_probability"], 20)
        cold = score_drain(funds_usd=5_000_000, known_safe=True, invariant_results=[{
            "id": "erc4626-solvency", "status": "failed",
        }])
        self.assertEqual(cold["drain_probability"], 0)
        self.assertFalse(cold["profit_invariant_broke"])

    def test_leaky_fixture_fires_profit_invariant(self):
        leaked = simulate_local_vault("leaky")
        self.assertTrue(leaked["profit_invariant_broke"])
        self.assertGreaterEqual(leaked["drain_probability"], 85)
        self.assertEqual(leaked["invariant"]["status"], "failed")
        self.assertNotIn("0x", leaked["invariant"]["evidence"])
        promote, why = should_promote_lane_b(
            funds_usd=50_000,
            invariant_results=[leaked["invariant"]],
        )
        self.assertTrue(promote, why)

    def test_accounting_quirk_ranks_low(self):
        inv = [{
            "id": "erc4626-solvency",
            "status": "failed",
            "evidence": "convertToAssets above totalAssets",
        }]
        scored = score_drain(funds_usd=12_000, invariant_results=inv)
        self.assertFalse(scored["profit_invariant_broke"])
        self.assertLessEqual(scored["drain_probability"], 15)
        promote, _ = should_promote_lane_b(funds_usd=12_000, invariant_results=inv)
        self.assertFalse(promote)
        heat, bd = evidence_heat(funds_usd=12_000, invariant_results=inv)
        self.assertGreater(heat, 0)
        self.assertLessEqual(bd["drain_probability"], 15)
        self.assertFalse(bd["profit_invariant_broke"])

    def test_setup_crash_adds_nothing(self):
        inv = [{"id": "fuzz-setUp()", "status": "failed", "source": "fuzz", "evidence": "property failed: setUp()"}]
        scored = score_drain(funds_usd=200_000, invariant_results=inv)
        self.assertEqual(scored["drain_probability"], 0)
        self.assertFalse(scored["profit_invariant_broke"])
        heat, bd = evidence_heat(funds_usd=200_000, invariant_results=inv, corroborated=[{
            "lead_id": "fuzz-setUp()", "confirmed": True, "method": "fuzz",
        }])
        self.assertEqual(heat, 0)
        self.assertEqual(bd["drain_probability"], 0)


if __name__ == "__main__":
    unittest.main()
