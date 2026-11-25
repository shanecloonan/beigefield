"""Dealt balances and price perturbations. Local math, no RPC."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.fork_verify import PLANT_ADDRESS, write_fork_verify_project
from eth_scanner.logic.perturb import chainlink_delta, perturbation_heat, run_perturbations, spot_skew_delta
from eth_scanner.logic.sequences import run_sequence_invariants


class Perturb(unittest.TestCase):
    def test_a_huge_balance_does_not_fail_a_fair_vault(self):
        report = run_sequence_invariants("fair", start_balance=10**24)
        self.assertTrue(all(row["status"] == "held" for row in report["results"]))
        self.assertEqual(report["start_balance"], 10**24)

    def test_spot_and_chainlink_increase_the_payout(self):
        self.assertGreater(spot_skew_delta(), 1)
        self.assertGreater(chainlink_delta(10), 1)
        self.assertLessEqual(chainlink_delta(0), 0)
        report = run_perturbations()
        failed = {row["id"] for row in report["results"] if row["status"] == "failed"}
        self.assertEqual(failed, {"profit-spot-reserve", "profit-chainlink-answer"})
        self.assertEqual(report["funded_failures"], [])
        heat, bd, _report = perturbation_heat()
        self.assertGreaterEqual(heat, 3)
        self.assertLessEqual(heat, 12)
        self.assertTrue(bd["profit_invariant_broke"])
        for row in report["results"]:
            self.assertNotIn("0x", row["evidence"])

    def test_harness_deals_and_overrides_only_the_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, props = write_fork_verify_project(
                Path(tmp) / "fv",
                address=PLANT_ADDRESS,
                source="function poke() external {}",
            )
            sol = (root / "test" / "ForkVerifyProperties.t.sol").read_text(encoding="utf-8")
            vm = (root / "lib" / "forge-std" / "src" / "Vm.sol").read_text(encoding="utf-8")
        self.assertIn("test_funded_perturbed_outsider_cannot_extract", sol)
        self.assertIn("1_000_000 ether", sol)
        self.assertIn("mockCall", sol)
        self.assertIn("external feed", sol.lower())
        self.assertIn("function mockCall", vm)
        self.assertNotIn("function attack", sol.lower())
        self.assertIn("funded_perturbed_outsider_cannot_extract", props)


if __name__ == "__main__":
    unittest.main()
