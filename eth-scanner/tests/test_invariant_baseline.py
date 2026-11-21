"""Baseline gate for defensive invariants. No model call and no heat without a local failure."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.invariants import judge, report


class InvariantBaseline(unittest.TestCase):
    def test_an_unknown_proposal_is_dropped_and_adds_no_heat(self):
        result = judge(["drain-the-vault", "erc4626-solvency"])
        self.assertEqual(result["kept"], ["erc4626-solvency"])
        self.assertEqual(result["dropped"][0]["id"], "drain-the-vault")
        self.assertEqual(result["heat_contribution"], 0)

    def test_a_baseline_failure_is_dropped_even_when_the_target_fails_too(self):
        result = judge(
            ["erc4626-solvency"],
            baseline_failures={"erc4626-solvency"},
            local_failures={"erc4626-solvency"},
        )
        self.assertEqual(result["kept"], [])
        self.assertEqual(result["reproduced"], [])
        self.assertEqual(result["heat_contribution"], 0)
        self.assertIn("baseline", result["dropped"][0]["reason"])

    def test_heat_moves_only_for_a_local_reproduction(self):
        quiet = judge(["lending-cash-borrows"], local_failures=set())
        self.assertEqual(quiet["heat_contribution"], 0)
        failed = judge(["lending-cash-borrows"], local_failures={"lending-cash-borrows"})
        self.assertEqual(failed["reproduced"], ["lending-cash-borrows"])
        self.assertEqual(failed["heat_contribution"], 1)

    def test_without_a_key_the_command_skips(self):
        saved = {name: os.environ.pop(name, None) for name in ("OPENAI_API_KEY", "ETH_SCANNER_LLM_API_KEY")}
        try:
            result = report(None)
        finally:
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["heat_contribution"], 0)
        self.assertEqual(result["kept"], [])


if __name__ == "__main__":
    unittest.main()
