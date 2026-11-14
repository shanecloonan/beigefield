"""Medusa is evidence unless a fork check shows the caller gained value."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.findings import apply_agreement
from eth_scanner.deep.medusa_runner import (
    findings_from_medusa,
    fork_profit_results,
    parse_medusa_output,
    run_medusa,
)
from eth_scanner.deep.strong import heat_if_live_confirmed
from eth_scanner.drain import simulate_local_vault
from eth_scanner.known_safe import is_known_safe

LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"


class MedusaParse(unittest.TestCase):
    def test_setup_crash_is_not_a_failed_property(self):
        self.assertEqual(parse_medusa_output("[FAIL] setUp() compilation failed"), [])
        heat, changed, _ = heat_if_live_confirmed(0, 50_000, [])
        self.assertEqual(heat, 0)
        self.assertFalse(changed)

    def test_property_without_caller_profit_adds_no_heat(self):
        text = "[FAIL] test_solvency_assets_cover_shares\nAssertion failed"
        rows = parse_medusa_output(text)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["caller_profit"])
        findings = findings_from_medusa(text)
        self.assertEqual(fork_profit_results(findings), [])
        heat, changed, _ = heat_if_live_confirmed(2, 80_000, [])
        self.assertEqual(heat, 2)
        self.assertFalse(changed)

    def test_leaky_vault_caller_profit_raises_heat(self):
        leaked = simulate_local_vault("leaky")
        self.assertTrue(leaked["profit_invariant_broke"])
        delta = int(leaked["invariant"]["attacker_delta"])
        text = (
            "[FAIL] test_no_third_party_balance_drop\n"
            "caller_profit_delta=%s\n" % delta
        )
        findings = findings_from_medusa(text)
        proofs = fork_profit_results(findings)
        self.assertEqual(len(proofs), 1)
        heat, changed, bd = heat_if_live_confirmed(0, 50_000, proofs)
        self.assertTrue(changed)
        self.assertGreaterEqual(heat, 3)
        self.assertTrue(bd["profit_invariant_broke"])
        self.assertNotIn("0x", proofs[0]["evidence"])

    def test_safe_vault_does_not_fire(self):
        safe = simulate_local_vault("safe")
        self.assertFalse(safe["profit_invariant_broke"])
        text = "[PASS] test_no_third_party_balance_drop\ncaller_profit_delta=0\n"
        self.assertEqual(fork_profit_results(findings_from_medusa(text)), [])
        heat, changed, bd = heat_if_live_confirmed(0, 50_000, [])
        self.assertEqual(heat, 0)
        self.assertFalse(changed)
        self.assertFalse(bd.get("profit_invariant_broke"))

    def test_known_safe_stays_cold_and_agreement_is_not_heat(self):
        self.assertTrue(is_known_safe(address=LINK, contract_name="LinkToken")[0])
        a = findings_from_medusa("[FAIL] test_solvency_assets_cover_shares")
        b = findings_from_medusa("[FAIL] test_solvency_assets_cover_shares")
        b[0].engine = "echidna"
        ranked = apply_agreement(a + b)
        self.assertGreaterEqual(ranked[0].agreement_count, 2)
        heat, changed, _ = heat_if_live_confirmed(0, 5_000_000, fork_profit_results(ranked))
        self.assertEqual(heat, 0)
        self.assertFalse(changed)

    def test_missing_binary_skips(self):
        report = run_medusa(suite_dir=ROOT / "research" / "fuzz", timeout_s=1)
        self.assertIn(report.status, {"skipped", "ok", "error"})
        if report.status == "skipped":
            self.assertEqual(report.findings, [])


if __name__ == "__main__":
    unittest.main()
