"""Multi-call sequence invariants. Local models only — no RPC."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.logic.sequences import MAX_DEPTH, MAX_SEQUENCES, SEQUENCES, run_sequence_invariants, sequence_heat


def _failed(report: dict) -> set[str]:
    return {row["id"] for row in report["results"] if row["status"] == "failed"}


class Catalog(unittest.TestCase):
    def test_catalog_is_capped_and_includes_a_single_call(self):
        self.assertLessEqual(len(SEQUENCES), MAX_SEQUENCES)
        self.assertTrue(any(len(seq) == 1 for seq in SEQUENCES))
        self.assertTrue(any(len(seq) > 1 for seq in SEQUENCES))
        for seq in SEQUENCES:
            self.assertLessEqual(len(seq), MAX_DEPTH)

    def test_fair_model_holds(self):
        heat, _bd, report = sequence_heat("fair")
        self.assertEqual(heat, 0)
        self.assertEqual(_failed(report), set())

    def test_dilute_breaks_share_price_only(self):
        report = run_sequence_invariants("dilute")
        self.assertEqual(_failed(report), {"share-price-monotonic"})
        heat, bd, _report = sequence_heat("dilute")
        self.assertGreater(heat, 0)
        self.assertGreater(bd["invariants_failed"], 0)
        self.assertFalse(bd["profit_invariant_broke"])

    def test_inflation_and_leaky_raise_attacker_balance(self):
        for model in ("inflation", "leaky"):
            report = run_sequence_invariants(model)
            self.assertIn("profit-attacker-balance", _failed(report), model)
            profit = next(row for row in report["results"] if row["id"] == "profit-attacker-balance")
            self.assertGreater(profit["attacker_delta"], 0)
            self.assertNotIn("0x", profit["evidence"])

    def test_short_breaks_solvency_without_profit(self):
        report = run_sequence_invariants("short")
        self.assertIn("erc4626-asset-shortfall", _failed(report))
        self.assertNotIn("profit-attacker-balance", _failed(report))

    def test_unknown_model_stays_fair(self):
        report = run_sequence_invariants("admin-key")
        self.assertEqual(report["model"], "fair")
        self.assertEqual(_failed(report), set())


class Harness(unittest.TestCase):
    def test_fork_harness_checks_views_inside_the_sequence(self):
        import tempfile
        from eth_scanner.engines.fork_verify import PLANT_ADDRESS, write_fork_verify_project

        with tempfile.TemporaryDirectory() as tmp:
            root, props = write_fork_verify_project(
                Path(tmp) / "fv",
                address=PLANT_ADDRESS,
                source="function poke() external {}",
            )
            sol = (root / "test" / "ForkVerifyProperties.t.sol").read_text(encoding="utf-8")
        self.assertIn("erc4626-asset-shortfall", sol)
        self.assertIn("share-price-monotonic", sol)
        self.assertIn("testFuzz_unprivileged_sequence_cannot_extract", sol)
        self.assertIn("test_unprivileged_known_selectors_cannot_extract", sol)
        self.assertNotIn("function attack", sol.lower())
        self.assertNotIn("vm.broadcast", sol.lower())
        self.assertIn("erc4626-asset-shortfall", props)
        self.assertIn("share-price-monotonic", props)


if __name__ == "__main__":
    unittest.main()
